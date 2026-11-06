from himari import db, persona, config
def test_memory_roundtrip():
    db.add_memory("unique_test_fact_123","test")
    assert any("unique_test_fact_123" in m["text"] for m in db.memories())
def test_persona():
    msgs=persona.build([{"role":"user","content":"hi"}],[])
    assert msgs[0]["role"]=="system"
def test_config():
    cfg=config.load(); assert "ollama" in cfg

def test_clear_session_removes_messages_and_summaries(tmp_path):
    original_dir = db.APP_DIR
    original_db = db.DB
    try:
        db.APP_DIR = tmp_path
        db.DB = tmp_path / "himari.db"
        db.add_message("demo", "user", "old conversation")
        db.save_summary("demo", "old summary")

        db.clear_session("demo")

        assert db.history("demo") == []
        assert db.summary_for_session("demo") == ""
    finally:
        db.APP_DIR = original_dir
        db.DB = original_db
