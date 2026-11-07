import time

from umdlibrary.jobs import runner
from umdlibrary.jobs.watch import Watcher


def test_run_now_states():
    jm = runner.JobManager()
    job = jm.submit("x", "works", lambda j: (j.set_progress(1, 2, "half"), j.log("hi"), "result")[-1])
    assert job.state == "queued" and job.to_dict()["percent"] == 0
    jm.run_now(job, lambda j: (j.set_progress(1, 2, "half"), j.log("hi"), "result")[-1])
    assert job.state == "done" and job.result == "result" and job.progress == job.total == 2
    assert job.to_dict()["percent"] == 100 and job.lines and "hi" in job.lines[0]
    bad = jm.submit("x", "fails", None)
    jm.run_now(bad, lambda j: 1 / 0)
    assert bad.state == "failed" and "ZeroDivisionError" in bad.error and bad.ended_at
    assert [j.id for j in jm.all()] == [2, 1]


def test_unique_and_cancel():
    jm = runner.JobManager()
    a = jm.submit("scan", "one", lambda j: None, unique=True)
    b = jm.submit("scan", "two", lambda j: None, unique=True)
    assert a is b and len(jm.all()) == 1
    assert jm.cancel(a.id) and a.state == "cancelled"
    assert not jm.cancel(a.id) and not jm.cancel(999)
    c = jm.submit("scan", "three", lambda j: None, unique=True)
    assert c is not a

    def long(job):
        for i in range(100):
            job.set_progress(i, 100)
            if i == 3:
                job.cancel_requested = True
    jm.run_now(c, long)
    assert c.state == "cancelled" and c.progress == 4


def test_worker_thread_runs_jobs():
    jm = runner.JobManager()
    jm.start()
    job = jm.submit("x", "threaded", lambda j: "ok")
    for _ in range(100):
        if job.state == "done":
            break
        time.sleep(0.02)
    assert job.state == "done" and job.result == "ok"
    jm.stop()


def test_watcher_status_and_trigger(monkeypatch):
    calls = []
    enabled = {"on": False}
    w = Watcher(lambda title: calls.append(title), lambda: enabled["on"], lambda: 5)
    assert w.status() == {"enabled": False, "interval": 5, "last_run": None, "next_in": None}
    enabled["on"] = True
    w.start()
    for _ in range(100):
        if calls:
            break
        w.next_run = time.time() - 1
        time.sleep(0.05)
    w.stop()
    assert calls[:1] == ["watch folder: scheduled scan"] and w.status()["next_in"] <= 5
    assert w.status()["last_run"] is not None
