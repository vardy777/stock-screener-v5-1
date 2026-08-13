from pathlib import Path
def test_v4_scheduled_adapter_permanently_rejects_notification_tasks_before_runner():
    text=(Path(__file__).resolve().parents[1]/"v4/scripts/p4_task_adapter.py").read_text(encoding="utf-8")
    guard=text.index('if args.task_name in {"morning_push","confirmation_push"}')
    runner=text.index('result=run(')
    assert guard<runner and "V4_NOTIFICATION_RETIRED_V5_ONLY" in text
