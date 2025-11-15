from expert_core import EXPERTS, start_expert_session, run_expert_turn


def conversation_loop(expert_key: str):
    expert = EXPERTS[expert_key]
    print(f"\n=== Talking to {expert['description']} ===")

    print(
        "Type your message to the expert.\n"
        "Commands:\n"
        "  :save  -> lock in the current plan to JSON for this expert\n"
        "  :back  -> go back to main menu without saving\n"
    )

    messages, greeting, has_saved_state = start_expert_session(expert_key)

    if has_saved_state:
        print(
            f"(Note: A saved {expert_key} plan already exists and will be used as starting context.)\n"
        )

    print(f"{expert['description']}: {greeting}\n")

    while True:
        user_msg = input("You (:save, :back): ").strip()
        if not user_msg:
            continue

        messages, assistant_text, saved = run_expert_turn(
            expert_key, messages, user_msg
        )
        command = user_msg.lower()

        if command == ":back":
            print("\nReturning to main menu without saving.\n")
            break

        if command == ":save":
            print(f"\n{assistant_text}\n")
            continue

        if assistant_text:
            print(f"\n{expert['description']}: {assistant_text}\n")


def main():
    while True:
        print("Choose expert:")
        for key in EXPERTS:
            print(f"  - {key}")
        print("  - quit")

        choice = input("> ").strip().lower()

        if choice in {"quit", "q", "exit"}:
            print("Exiting. Bye!\n")
            break

        if choice not in EXPERTS:
            print("Invalid choice, please try again.\n")
            continue

        conversation_loop(choice)


if __name__ == "__main__":
    main()
