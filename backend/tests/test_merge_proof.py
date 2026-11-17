"""合并证明实体：按合并批次 id 的只读接口，四值（合并前/后 已对外/暂存）同源派生。"""

from pathlib import Path
import os
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["DATA_DIR"] = str(ROOT / "backend" / "data_test")
os.environ["FIXTURES_DIR"] = str(ROOT / "fixtures")

db_path = Path(os.environ["DATA_DIR"]) / "app.db"
if db_path.exists():
    db_path.unlink()

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _accounts(client):
    return {a["code"]: a for a in client.get("/api/accounts").json()}


def _totals(accounts):
    posted = sum(a["posted_cents"] for a in accounts.values())
    staging = sum(a["staging_cents"] for a in accounts.values())
    return posted, staging, posted + staging


def test_proof_endpoint_is_read_only_and_404_for_unknown_batch(client):
    assert client.get("/api/balance-merges/999999").status_code == 404
    # 只读接口：不暴露任何写动作，批次列表仍可匿名读
    assert client.get("/api/balance-merges").status_code == 200


def test_merge_proof_captures_pre_post_balances_per_account(client):
    before = _accounts(client)
    pre_posted, pre_staging, pre_total = _totals(before)

    run = client.post("/api/settle-runs")
    assert run.status_code == 200, run.text
    settled = _accounts(client)
    mid_posted, mid_staging, mid_total = _totals(settled)
    # 归并只写暂存：已对外分文不动
    assert mid_posted == pre_posted
    assert mid_staging != 0

    merge = client.post("/api/balance-merges")
    assert merge.status_code == 200, merge.text
    body = merge.json()
    mid = body["id"]

    # 按合并批次 id 查询的只读证明接口
    got = client.get(f"/api/balance-merges/{mid}")
    assert got.status_code == 200
    proof = got.json()["证明"]

    # 证明四值：合并前/后 已对外/暂存
    assert proof["合并批次id"] == mid
    assert proof["合并前已对外分"] == mid_posted
    assert proof["合并前暂存分"] == mid_staging
    assert proof["合并后已对外分"] == mid_posted + mid_staging
    assert proof["合并后暂存分"] == 0
    assert proof["对外口径"] == "已对外余额"

    # 批次头表同值落库，不只是展示口径
    assert body["posted_before_cents"] == mid_posted
    assert body["staging_before_cents"] == mid_staging
    assert body["posted_after_cents"] == mid_posted + mid_staging
    assert body["staging_after_cents"] == 0

    # 分户证明：与账户实际双列同源，逐户给齐合并前/后
    staged_codes = {c for c, a in settled.items() if a["staging_cents"] != 0}
    assert len(proof["分户"]) == len(staged_codes)
    after = _accounts(client)
    for line in proof["分户"]:
        code = line["account_code"]
        assert code in staged_codes
        assert line["合并前已对外分"] == settled[code]["posted_cents"]
        assert line["合并前暂存分"] == settled[code]["staging_cents"]
        assert line["合并后已对外分"] == after[code]["posted_cents"]
        assert line["合并后暂存分"] == 0
        assert after[code]["staging_cents"] == 0
        # 同源派生：后值 = 前已对外 + 前暂存
        assert line["合并后已对外分"] == (
            line["合并前已对外分"] + line["合并前暂存分"]
        )


def test_balances_and_proof_share_one_source_after_merge(client):
    """证明与账户双列同源：库里只有一套 posted/staging，证明是其快照不是第二套余额。"""
    client.post("/api/settle-runs")
    merge = client.post("/api/balance-merges").json()
    accounts = _accounts(client)
    posted, staging, total = _totals(accounts)

    assert merge["证明"]["合并后已对外分"] == posted
    assert merge["证明"]["合并后暂存分"] == staging == 0
    # 合并后合计不变，只是在两套余额间搬家
    assert merge["posted_after_cents"] == total


def test_failed_merge_leaves_no_proof_and_no_balance_pollution(client):
    """合并失败不得留下本趟污染，失败批次整体回滚、不产生证明。"""
    # 前置：直接补一笔待归并正向流水，确保存在待合并暂存可触发演练失败。
    from app.db import DB_PATH
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO ledger_entries(
          entry_key, account_id, kind, amount_cents, biz_ref,
          target_entry_key, booked_at, status, note
        ) VALUES ('FWD-PROOF-FAIL', 1, '正向', 700, '', NULL,
                  '2026-11-17T00:00:00Z', '待归并', '失败演练前置')
        """
    )
    conn.commit()
    conn.close()

    assert client.post("/api/settle-runs").status_code == 200
    before = _accounts(client)
    assert any(a["staging_cents"] for a in before.values())

    r = client.post("/api/balance-merges?simulate_failure=true")
    assert r.status_code == 500
    after = _accounts(client)
    assert {k: (v["posted_cents"], v["staging_cents"]) for k, v in after.items()} == {
        k: (v["posted_cents"], v["staging_cents"]) for k, v in before.items()
    }
    # 失败批次整体回滚：列表里只剩完成态，且最新证明仍是上一批成功合并
    batches = client.get("/api/balance-merges").json()
    assert all(m["status"] == "完成" for m in batches)
    latest = max(m["id"] for m in batches)
    got = client.get(f"/api/balance-merges/{latest}").json()
    assert got["证明"]["合并后暂存分"] == 0


def test_failed_settle_leaves_no_staging_pollution(client):
    before = _accounts(client)
    r = client.post("/api/settle-runs?simulate_failure=true")
    assert r.status_code == 500
    after = _accounts(client)
    assert {k: (v["posted_cents"], v["staging_cents"]) for k, v in after.items()} == {
        k: (v["posted_cents"], v["staging_cents"]) for k, v in before.items()
    }


def test_external_basis_never_uses_total_as_posted(client):
    """硬约束：对外读接口/互证返回不得拿合计冒充 posted。"""
    # 再造一笔待归并并落暂存，使 posted 与 staging 同时非零以便区分
    from app.db import DB_PATH
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO ledger_entries(
          entry_key, account_id, kind, amount_cents, biz_ref,
          target_entry_key, booked_at, status, note
        ) VALUES ('FWD-PROOF-BASIS', 2, '正向', 900, '', NULL,
                  '2026-11-17T01:00:00Z', '待归并', '口径核对前置')
        """
    )
    conn.commit()
    conn.close()
    client.post("/api/settle-runs")

    accounts = _accounts(client)
    posted, staging, total = _totals(accounts)
    assert staging != 0 and total != posted

    d = client.get("/api/dashboard").json()
    assert d["对外口径"] == "已对外余额"
    assert d["已对外余额合计分"] == posted
    assert d["暂存余额合计分"] == staging
    assert d["余额合计分"] == total
    assert d["已对外余额合计分"] != d["余额合计分"]

    report = client.post("/api/verify-reports").json()
    assert report["basis"] == "已对外余额"
    assert report["posted_cents"] == posted
    assert report["staging_cents"] == staging
    assert report["detail"]["对外口径"] == "已对外余额"
    assert report["detail"]["已对外余额分"] == posted
    assert report["detail"]["双余额合计分"] == total

    staging_view = client.get("/api/staging").json()
    assert staging_view["对外口径"] == "已对外余额"
    assert staging_view["合计"]["posted_cents"] == posted
    assert staging_view["合计"]["staging_cents"] == staging

    # 账户接口分列两套余额，没有把合计塞进已对外
    for a in client.get("/api/accounts").json():
        assert a["total_cents"] == a["posted_cents"] + a["staging_cents"]


def test_empty_merge_still_writes_self_consistent_proof(client):
    # 先清掉前置测试可能残留的暂存，再验真正的空合并
    client.post("/api/balance-merges")
    before = _accounts(client)
    assert all(a["staging_cents"] == 0 for a in before.values())

    body = client.post("/api/balance-merges").json()
    assert body["account_count"] == 0
    assert body["staged_total_cents"] == 0
    proof = body["证明"]
    assert proof["合并前已对外分"] == proof["合并后已对外分"]
    assert proof["合并前暂存分"] == proof["合并后暂存分"] == 0
    assert proof["分户"] == []
    after = _accounts(client)
    assert {k: v["posted_cents"] for k, v in after.items()} == {
        k: v["posted_cents"] for k, v in before.items()
    }
