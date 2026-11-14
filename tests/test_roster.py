import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROSTER = json.loads((ROOT / "config/agents.json").read_text())
AGENTS_MD = (ROOT / "docs/agents.md").read_text()


def test_every_agent_and_key_of_the_roster_is_in_agents_md():
    for agent in ROSTER["agents"]:
        assert agent["switch"] in AGENTS_MD and agent["key"] in AGENTS_MD, agent["id"]
    for key in ROSTER["keys"]:
        assert key["name"] in AGENTS_MD and key["money_cap"] in AGENTS_MD, key["name"]


def test_at_most_eight_agents_run_a_model():
    assert sum(agent["model"] for agent in ROSTER["agents"]) <= 8
