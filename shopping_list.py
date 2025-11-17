from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import json


REPO_ROOT = Path(__file__).resolve().parent
RECIPES_PATH = REPO_ROOT / "recipes.json"
PANTRY_PATH = REPO_ROOT / "pantry.json"
NUTRITION_PATH = REPO_ROOT / "nutrition.json"


def load_json(path: Path, default: Any) -> Any:
    """
    Load JSON from the given path.
    Returns `default` if the file does not exist or is invalid.
    """
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def load_recipes() -> Dict[str, Any]:
    """
    Load recipes.json and return a mapping of recipe_id -> recipe dict.

    Expected shape (from Recipe Expert):
    {
      "schema_version": 1,
      "recipes": [ { recipe_dict }, ... ]
    }
    """
    data = load_json(RECIPES_PATH, {"schema_version": 1, "recipes": []})
    recipes_list = data.get("recipes") or []
    recipes_by_id: Dict[str, Any] = {}
    for r in recipes_list:
        rid = r.get("id")
        if isinstance(rid, str):
            recipes_by_id[rid] = r
    return recipes_by_id


def load_pantry() -> Dict[str, Any]:
    """
    Load pantry.json and return a mapping of normalized name -> pantry item dict.

    Expected shape (from Pantry Expert):
    {
      "schema_version": 1,
      "items": [ { pantry_item }, ... ]
    }

    For now we key by lowercased `name`; later we can add more robust mapping.
    """
    data = load_json(PANTRY_PATH, {"schema_version": 1, "items": []})
    items_list = data.get("items") or []
    by_name: Dict[str, Any] = {}
    for item in items_list:
        name = item.get("name")
        if isinstance(name, str):
            by_name[name.strip().lower()] = item
    return by_name


def load_nutrition() -> Dict[str, Any]:
    """
    Load nutrition.json and return its top-level object.

    This may include the optional "recipe_links" mapping.
    """
    return load_json(NUTRITION_PATH, {})


def extract_recipe_servings_from_nutrition(
    nutrition: Dict[str, Any]
) -> Dict[str, int]:
    """
    Inspect nutrition["recipe_links"] and aggregate planned servings per recipe.
    """
    recipe_links = nutrition.get("recipe_links") or {}
    if not isinstance(recipe_links, dict):
        return {}

    totals: Dict[str, int] = defaultdict(int)

    for day_name, meals in recipe_links.items():
        if not isinstance(meals, dict):
            continue
        for meal_slot, info in meals.items():
            if not isinstance(info, dict):
                continue

            rid = info.get("recipe_id")
            servings = info.get("servings", 1)

            if not isinstance(rid, str) or not rid.strip():
                continue

            try:
                servings_int = int(servings)
            except (TypeError, ValueError):
                servings_int = 1

            if servings_int <= 0:
                continue

            totals[rid] += servings_int

    return dict(totals)


def aggregate_ingredients(
    recipes: Dict[str, Any],
    recipe_servings: Dict[str, int],
) -> List[Dict[str, Any]]:
    """
    Aggregate ingredient requirements across multiple recipes.

    recipe_servings: mapping from recipe_id -> how many servings you plan to make.
    """
    totals: Dict[tuple, float] = defaultdict(float)

    for recipe_id, servings in recipe_servings.items():
        if servings <= 0:
            continue

        recipe = recipes.get(recipe_id)
        if not recipe:
            continue

        ingredients = recipe.get("ingredients") or []
        for ing in ingredients:
            name = ing.get("name")
            amount = ing.get("amount")
            unit = ing.get("unit")

            if not isinstance(name, str) or not isinstance(unit, str):
                continue
            try:
                base_amount = float(amount)
            except (TypeError, ValueError):
                continue

            key = (name.strip(), unit.strip())
            totals[key] += base_amount * float(servings)

    result: List[Dict[str, Any]] = []
    for (name, unit), total_amount in totals.items():
        result.append(
            {
                "name": name,
                "unit": unit,
                "total_amount": round(total_amount, 2),
            }
        )
    # Sort by ingredient name for nicer output
    result.sort(key=lambda x: x["name"].lower())
    return result


def annotate_with_pantry(
    aggregated: List[Dict[str, Any]],
    pantry_by_name: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Add pantry information (is_staple, status) to each aggregated ingredient
    when we can match it by name.
    """
    annotated: List[Dict[str, Any]] = []

    for item in aggregated:
        name = item["name"]
        key = name.strip().lower()
        pantry_item = pantry_by_name.get(key)

        if pantry_item:
            is_staple = pantry_item.get("is_staple")
            status = pantry_item.get("status") or "unknown"
        else:
            is_staple = None
            status = "unknown"

        annotated.append(
            {
                **item,
                "pantry_status": status,
                "pantry_is_staple": bool(is_staple) if is_staple is not None else None,
            }
        )

    return annotated


def format_shopping_list(annotated: List[Dict[str, Any]]) -> str:
    """
    Produce a human-readable shopping list text from annotated items.
    """
    if not annotated:
        return "No ingredients found for the given recipes."

    need: List[str] = []
    staples: List[str] = []
    other: List[str] = []

    for item in annotated:
        name = item["name"]
        amount = item["total_amount"]
        unit = item["unit"]
        status = item["pantry_status"]
        is_staple = item["pantry_is_staple"]

        line = f"- {name}: {amount} {unit} (pantry: {status})"

        if status in {"out", "low"}:
            need.append(line)
        elif status == "in_stock" and is_staple:
            staples.append(line)
        elif status == "unknown":
            need.append(line + " [check at home]")
        else:
            other.append(line)

    sections: List[str] = []

    if need:
        sections.append("## Need to buy\n" + "\n".join(need))
    if staples:
        sections.append("## Probably already have (staples)\n" + "\n".join(staples))
    if other:
        sections.append("## Other / uncategorised\n" + "\n".join(other))

    return "\n\n".join(sections)


def generate_shopping_list_for_plan(
    recipe_servings: Dict[str, int],
) -> str:
    """
    High-level API:
    - Load recipes and pantry.
    - Aggregate ingredients for the given recipe_servings.
    - Annotate with pantry info.
    """
    recipes = load_recipes()
    pantry_by_name = load_pantry()

    aggregated = aggregate_ingredients(recipes, recipe_servings)
    annotated = annotate_with_pantry(aggregated, pantry_by_name)
    return format_shopping_list(annotated)


def aggregate_ingredients_from_nutrition_meals(
    nutrition: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Walk nutrition.json and aggregate ingredients from any meal structures.
    """
    totals: Dict[tuple, float] = defaultdict(float)

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            meals = obj.get("meals")
            if isinstance(meals, list):
                for meal in meals:
                    if not isinstance(meal, dict):
                        continue
                    items = meal.get("items") or []
                    if not isinstance(items, list):
                        continue
                    for ing in items:
                        if not isinstance(ing, dict):
                            continue
                        name = ing.get("name")
                        if not isinstance(name, str):
                            continue
                        amount = ing.get("amount_g")
                        if amount is None:
                            amount = ing.get("amount_ml")
                        try:
                            amount_f = float(amount)
                        except (TypeError, ValueError):
                            continue
                        key = (name.strip(), "g")
                        totals[key] += amount_f
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(nutrition)

    result: List[Dict[str, Any]] = []
    for (name, unit), total_amount in totals.items():
        result.append(
            {"name": name, "unit": unit, "total_amount": round(total_amount, 2)}
        )
    result.sort(key=lambda x: x["name"].lower())
    return result


def generate_shopping_list_from_nutrition(
    nutrition: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Generate a shopping list using nutrition.json (recipe_links + direct meals).
    """
    if nutrition is None:
        nutrition = load_nutrition()

    recipes = load_recipes()
    pantry_by_name = load_pantry()

    recipe_servings = extract_recipe_servings_from_nutrition(nutrition)
    aggregated_from_recipes: List[Dict[str, Any]] = []
    if recipe_servings:
        aggregated_from_recipes = aggregate_ingredients(recipes, recipe_servings)

    aggregated_from_meals = aggregate_ingredients_from_nutrition_meals(nutrition)

    combined_totals: Dict[tuple, float] = defaultdict(float)
    for source_list in (aggregated_from_recipes, aggregated_from_meals):
        for item in source_list:
            name = item.get("name")
            unit = item.get("unit", "g")
            amount = item.get("total_amount", 0)
            if not isinstance(name, str):
                continue
            try:
                amount_f = float(amount)
            except (TypeError, ValueError):
                continue
            key = (name.strip(), unit.strip())
            combined_totals[key] += amount_f

    combined: List[Dict[str, Any]] = []
    for (name, unit), total_amount in combined_totals.items():
        combined.append(
            {"name": name, "unit": unit, "total_amount": round(total_amount, 2)}
        )
    combined.sort(key=lambda x: x["name"].lower())

    if not combined:
        return (
            "No ingredients found in nutrition plan.\n"
            "Ensure nutrition.json either includes a top-level 'recipe_links' "
            "mapping or defines meals/items with measurable quantities."
        )

    annotated = annotate_with_pantry(combined, pantry_by_name)
    return format_shopping_list(annotated)


if __name__ == "__main__":
    # Manual override: edit this dict to test specific recipe/servings combinations.
    example_recipe_servings = {
        # "chicken_rice_bowl": 4,
        # "oats_protein_breakfast": 7,
    }

    if example_recipe_servings:
        txt = generate_shopping_list_for_plan(example_recipe_servings)
        print(txt)
    else:
        txt = generate_shopping_list_from_nutrition()
        print(txt)
