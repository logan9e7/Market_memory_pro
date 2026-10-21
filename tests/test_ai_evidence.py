"""Cross-user and provenance guards for the LLM evidence boundary."""
import unittest
from app.ai_evidence import prepare_evidence

class EvidenceSecurityTests(unittest.TestCase):
    def test_valid_owner_scoped_evidence(self):
        data={"snapshots":[{"id":2,"user_id":7,"note":"Original snapshot"}],
              "decisions":[{"id":4,"user_id":7,"evidence_ref":"decision:4"}],
              "quotes":[]}
        selected=prepare_evidence(data,user_id=7)
        self.assertEqual(selected["snapshots"][0]["evidence_ref"],"snapshot:2")
        self.assertEqual(selected["decisions"][0]["evidence_ref"],"decision:4")

    def test_cross_owner_rejected(self):
        with self.assertRaises(PermissionError):
            prepare_evidence({"decisions":[{"id":4,"user_id":8}]},user_id=7)

    def test_mismatched_source_reference_rejected(self):
        with self.assertRaises(ValueError):
            prepare_evidence({"quotes":[{"id":4,"evidence_ref":"decision:4"}]},user_id=7)

    def test_invalid_limits(self):
        with self.assertRaises(ValueError):
            prepare_evidence({},user_id=7,max_per_kind=0)

if __name__=="__main__":
    unittest.main()
