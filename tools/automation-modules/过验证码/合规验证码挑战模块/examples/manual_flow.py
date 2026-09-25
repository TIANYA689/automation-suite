"""Run an authorized manual challenge flow without external dependencies."""

from captcha_challenge import (
    AuthorizationPolicy,
    ChallengeContext,
    ChallengeCoordinator,
    ChallengeKind,
    JsonLinesAuditSink,
    ManualChallengeProvider,
)


def main() -> None:
    target_url = "http://localhost:8000/authorized-test"
    provider = ManualChallengeProvider()
    coordinator = ChallengeCoordinator(
        [provider],
        AuthorizationPolicy(("localhost",)),
        timeout_seconds=120,
        audit_sink=JsonLinesAuditSink("audit/challenges.jsonl"),
    )
    context = ChallengeContext(
        session_id="local-demo-session",
        target_url=target_url,
        kind=ChallengeKind.INTERACTIVE,
        authorized=True,
        authorization_reference="local-owner-test",
    )

    ticket = coordinator.start(context)
    print(f"Challenge ticket: {ticket.ticket_id}")
    response = input("Complete the authorized challenge and enter its response: ")
    provider.submit(ticket.ticket_id, response)
    coordinator.wait(ticket.ticket_id)

    proof = coordinator.consume(
        ticket.ticket_id,
        session_id=context.session_id,
        target_url=context.target_url,
    )
    print(f"Response received once ({len(proof)} characters); value was not logged.")


if __name__ == "__main__":
    main()

