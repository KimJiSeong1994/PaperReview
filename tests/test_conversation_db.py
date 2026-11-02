"""ConversationDB: CRUD, exact-incarnation ownership, archive, deletion."""

from src.storage.conversation_db import ConversationDB


def test_crud_ownership_archive_and_delete(tmp_path):
    db = ConversationDB(tmp_path / "c.db")
    conv = db.create_conversation("alice", "inc1", "트랜스포머")
    user = db.append_turn(conv["id"], "user", "트랜스포머 논문")
    bot = db.append_turn(conv["id"], "assistant", "", status="running")
    assert (user["seq"], bot["seq"]) == (1, 2)

    blocks = [{"type": "search_results", "papers": [{"title": "Attention"}]}]
    db.finish_turn(bot["id"], "요약", blocks, "search", "done", "m", 12)
    got = db.get_conversation(conv["id"], "alice", "inc1")
    assert [t["role"] for t in got["turns"]] == ["user", "assistant"]
    assert got["turns"][1]["blocks"] == blocks and got["turns"][1]["status"] == "done"

    # Same username, other incarnation (re-registered account) or other user → None.
    assert db.get_conversation(conv["id"], "alice", "inc2") is None
    assert db.get_conversation(conv["id"], "bob", "inc1") is None

    listed = db.list_conversations("alice", "inc1")
    assert listed == [{"id": conv["id"], "title": "트랜스포머", "updated_at": listed[0]["updated_at"],
                       "turn_count": 2, "last_intent": "search"}]
    assert db.list_conversations("alice", "inc2") == []

    assert db.archive(conv["id"], "bob", "inc1") is False
    assert db.archive(conv["id"], "alice", "inc1") is True
    assert db.list_conversations("alice", "inc1") == []

    db.create_conversation("alice", "inc2", "두 번째")
    db.create_conversation("bob", "inc1", "남의 것")
    assert db.delete_by_username("alice") == 2
    assert db.list_conversations("bob", "inc1") != []


def test_running_turns_fail_on_restart(tmp_path):
    db = ConversationDB(tmp_path / "c.db")
    conv = db.create_conversation("alice", "inc1", "t")
    db.append_turn(conv["id"], "assistant", "", status="running")
    restarted = ConversationDB(tmp_path / "c.db")
    assert restarted.get_conversation(conv["id"], "alice", "inc1")["turns"][0]["status"] == "error"
