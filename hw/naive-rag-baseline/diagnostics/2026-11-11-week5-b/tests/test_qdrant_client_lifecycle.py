"""Regression tests for the reported crash:

    Storage folder .../naive-rag-baseline/.qdrant is already accessed by
    another instance of Qdrant client.

Root cause: run_phase5.run_naiv builds its own fresh local Qdrant client
per call when none is supplied, and never closes it -- so two sequential
naiv cases in the same process each opened a NEW client on the same
on-disk path without the previous one ever being closed.

Fix (measure.py): a single client shared across every naiv case in one
run (``shared_qdrant_client`` + ``build_real_gen_fns``'s ``qdrant_client``
parameter), closed exactly once via a context manager -- success or
MeasurementHalted alike.

None of these tests touch the project's real .qdrant directory; they use
either fakes or a real qdrant_client.QdrantClient pointed at a temporary
directory, with no model/embedding call anywhere.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import measure


class FakeQdrantClient:
    def __init__(self) -> None:
        self.closed = False
        self.close_count = 0

    def close(self) -> None:
        self.closed = True
        self.close_count += 1


class SharedQdrantClientContextManagerTests(unittest.TestCase):
    """Isolates measure.shared_qdrant_client from the real
    naive_rag.vectorstore._client factory -- these tests only check the
    open-once/close-exactly-once contract, never the real storage path."""

    def test_factory_called_once_and_client_closed_on_success(self) -> None:
        fake = FakeQdrantClient()
        factory = mock.Mock(return_value=fake)
        with mock.patch("naive_rag.vectorstore._client", factory):
            with measure.shared_qdrant_client() as client:
                self.assertIs(client, fake)
                self.assertFalse(fake.closed)
            self.assertTrue(fake.closed)
            self.assertEqual(fake.close_count, 1)
        factory.assert_called_once_with(register_close=False)

    def test_client_is_closed_even_when_the_body_raises(self) -> None:
        """This is the MeasurementHalted-mid-run scenario: a later naiv
        case (or any other case) raises, and the shared client must still
        be released so a subsequent invocation can reopen the same path."""
        fake = FakeQdrantClient()
        with mock.patch("naive_rag.vectorstore._client", return_value=fake):
            with self.assertRaises(measure.MeasurementHalted):
                with measure.shared_qdrant_client() as client:
                    raise measure.MeasurementHalted("Q07/naiv: generation failed")
            self.assertTrue(fake.closed)

    def test_two_sequential_uses_each_open_and_close_their_own_scope(self) -> None:
        """Simulates two separate run_measurement invocations (e.g. smoke
        then full, or a resume): each call to shared_qdrant_client() opens
        its own client and closes it before returning -- no leftover lock
        carried into the next invocation."""
        first_fake = FakeQdrantClient()
        second_fake = FakeQdrantClient()
        factory = mock.Mock(side_effect=[first_fake, second_fake])
        with mock.patch("naive_rag.vectorstore._client", factory):
            with measure.shared_qdrant_client():
                pass
            self.assertTrue(first_fake.closed)
            with measure.shared_qdrant_client():
                pass
            self.assertTrue(second_fake.closed)
        self.assertEqual(factory.call_count, 2)


class BuildRealGenFnsSharesOneClientTests(unittest.TestCase):
    """Proves build_real_gen_fns threads the SAME client object into every
    naiv case -- not a new one per question -- by faking
    generation_runner.run_naiv_capture and recording what it received."""

    def test_two_consecutive_naiv_cases_receive_the_identical_client(self) -> None:
        fake_client = FakeQdrantClient()
        received_clients = []

        def fake_run_naiv_capture(question_id, question_text, budget, ledger, *, run_phase, **inject):
            received_clients.append(inject.get("qdrant_client"))
            return {
                "question_id": question_id, "mode": "naiv", "run_phase": run_phase,
                "answer": "fake", "refused": None, "model_called": True,
                "actual_context": "ctx", "actual_chunk_ids": [], "chunk_ids_traceable": True,
                "is_proxy_retrieval": False, "error": None, "duration_seconds": 0.0,
            }

        with mock.patch("generation_runner.run_naiv_capture", fake_run_naiv_capture):
            gen_fns = measure.build_real_gen_fns(
                budget=None, ledger=None, reports=(), run_phase="smoke", qdrant_client=fake_client)
            gen_fns["naiv"](_FakeQuestion("Q01", "Question one?"))
            gen_fns["naiv"](_FakeQuestion("Q07", "Question two?"))

        self.assertEqual(len(received_clients), 2)
        self.assertIs(received_clients[0], fake_client)
        self.assertIs(received_clients[1], fake_client)
        self.assertFalse(fake_client.closed)  # closing is shared_qdrant_client's job, not naiv_fn's


class _FakeQuestion:
    def __init__(self, qid: str, text: str) -> None:
        self.id = qid
        self.question = text


class RealLocalQdrantLifecycleTests(unittest.TestCase):
    """Uses the real, installed qdrant_client library against a TEMPORARY
    on-disk path (never the project's own .qdrant/) to verify the actual
    open/close/reopen behaviour the fix relies on -- no model or embedding
    call anywhere in this class."""

    def test_second_open_without_closing_the_first_reproduces_the_reported_error(self) -> None:
        from qdrant_client import QdrantClient

        # ignore_cleanup_errors=True: on Windows, the FAILED second
        # QdrantClient(path=...) call below leaves its own open handle on
        # the storage folder's .lock file (a qdrant_client/Windows
        # file-locking quirk, not something this test or the fix controls)
        # until that second, never-fully-constructed client object is
        # garbage collected -- which can outlive this test's own scope and
        # otherwise fail the temp directory's teardown.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = str(Path(tmp) / "qdrant-data")
            first = QdrantClient(path=path)
            try:
                with self.assertRaises(RuntimeError) as ctx:
                    QdrantClient(path=path)
                self.assertIn("already accessed by another instance", str(ctx.exception))
            finally:
                first.close()

    def test_close_then_reopen_succeeds(self) -> None:
        from qdrant_client import QdrantClient

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "qdrant-data")
            first = QdrantClient(path=path)
            first.close()
            second = QdrantClient(path=path)  # must not raise now that `first` is closed
            second.close()

    def test_one_shared_client_serves_two_sequential_queries_without_reopening(self) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams

        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "qdrant-data")
            client = QdrantClient(path=path)
            try:
                client.create_collection("test", vectors_config=VectorParams(size=4, distance=Distance.COSINE))
                client.upsert("test", points=[
                    PointStruct(id=1, vector=[0.1, 0.2, 0.3, 0.4], payload={"chunk_id": "a#0"})])
                # Two sequential "cases" reusing the SAME client, as
                # build_real_gen_fns now does -- no reopen, no lock error.
                first = client.query_points("test", query=[0.1, 0.2, 0.3, 0.4], limit=1)
                second = client.query_points("test", query=[0.1, 0.2, 0.3, 0.4], limit=1)
                self.assertEqual(len(first.points), 1)
                self.assertEqual(len(second.points), 1)
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
