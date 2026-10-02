import unittest
from fastapi.testclient import TestClient
from backend.app import app

class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_system_status_endpoint(self):
        response = self.client.get("/api/system-status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["diagnostics"]["ready"])
        self.assertTrue(data["diagnostics"]["ffmpeg"]["available"])

    def test_queue_ingestion_and_clear(self):
        # Ingest track
        payload = {
            "raw_text": "Daft Punk - Get Lucky [Official Video]\nPink Floyd - Time (The Dark Side of the Moon)"
        }
        res = self.client.post("/api/queue/add", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data["jobs"]), 2)
        job1 = data["jobs"][0]
        self.assertEqual(job1["track"]["artist"], "Daft Punk")
        self.assertEqual(job1["track"]["title"], "Get Lucky")

        # Get queue snapshot
        get_res = self.client.get("/api/queue")
        self.assertEqual(get_res.status_code, 200)
        queue_data = get_res.json()
        self.assertGreaterEqual(queue_data["count"], 2)

        # Clear queue
        clear_res = self.client.post("/api/queue/clear?clear_all=true")
        self.assertEqual(clear_res.status_code, 200)

        get_res2 = self.client.get("/api/queue")
        self.assertEqual(get_res2.json()["count"], 0)

    def test_config_endpoints(self):
        res = self.client.get("/api/config")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["vbr_quality"], 0)
        self.assertEqual(data["sample_rate"], 44100)

    def test_library_endpoint(self):
        res = self.client.get("/api/library")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("tracks", data)
        self.assertIn("output_dir", data)

if __name__ == "__main__":
    unittest.main()
