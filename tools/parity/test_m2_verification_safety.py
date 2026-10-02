from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml
from tools.parity import verify_m2 as verifier
from tools.parity.normalize import normalize_event


def valid_case(case_id='model-low-confidence-fallback'):
    c = next(c for c in yaml.safe_load(verifier.SCENARIO_PATH.read_text(encoding='utf-8'))['cases'] if c['id'] == case_id)
    result = {'schema_version':'1.0','run_id':'run-1','scenario_id':'support-handoff','case_id':c['id'],'router_mode':c['router_mode'],'status':c['expected_status'],'proposed_route':c['expected_proposed_route'],'selected_route':c['expected_selected_route'],'receiver':c['expected_receiver'],'fallback_applied':c['expected_fallback_applied'],'specialist_invoked':c['expected_specialist_invoked'],'failure_code':c['expected_failure_code'],'trace_path':'/trace.jsonl'}
    requested = {'handoff_id':'h-1','sender':'support-router','receiver':c['expected_receiver'],'sender_intent':{'route':c['expected_proposed_route'],'confidence':c['expected_confidence'],'policy_outcome':c['expected_policy_outcome']},'receiver_input':{'ticket_id':c['ticket_id'],**({} if case_id == 'handoff-context-loss' else {'request_text':c['request']})}}
    payloads = [('run.created',{'scenario_id':'support-handoff','case_id':c['id'],'router_mode':c['router_mode']}),('run.started',{'case_id':c['id'],'router_mode':c['router_mode']})]
    if c['router_mode'] == 'model': payloads += [('model.requested',{'case_id':c['id']}),('model.completed',{'case_id':c['id'],'decision':{'route':c['expected_proposed_route'],'confidence':c['expected_confidence']}})]
    payloads += [('route.selected',{'router_mode':c['router_mode'],'proposed_route':c['expected_proposed_route'],'selected_route':c['expected_selected_route'],'confidence':c['expected_confidence'],'fallback_applied':c['expected_fallback_applied']}),('handoff.requested',requested)]
    payloads += [('handoff.accepted' if c['expected_specialist_invoked'] else 'handoff.rejected',{'handoff_id':'h-1','receiver':c['expected_receiver'],**({} if c['expected_specialist_invoked'] else {'failure_code':c['expected_failure_code']})})]
    payloads += [('run.completed' if c['expected_specialist_invoked'] else 'run.failed',{k:v for k,v in result.items() if k in ('status','proposed_route','selected_route','receiver','fallback_applied','specialist_invoked') or (k == 'failure_code' and v is not None)})]
    events = [{'schema_version':'1.0','event_id':f'e-{i}','run_id':'run-1','sequence':i,'type':t,'timestamp':'2026-09-30T00:00:00Z','source':'python','data':d} for i,(t,d) in enumerate(payloads,1)]
    return c,result,events


class VerificationSafety(unittest.TestCase):
    def test_normalizes_only_top_level_generated_handoff_id(self):
        left={'type':'handoff.requested','data':{'handoff_id':'a','receiver':'billing-specialist','receiver_input':{'handoff_id':'business'}}}
        right=deepcopy(left);right['data']['handoff_id']='b'
        self.assertEqual(normalize_event(left),normalize_event(right))
        right['data']['receiver']='general-specialist'
        self.assertNotEqual(normalize_event(left),normalize_event(right))
        self.assertEqual(left['data']['handoff_id'],'a')
        self.assertEqual(normalize_event(left)['data']['receiver_input']['handoff_id'],'business')
        other={'type':'tool.requested','data':{'handoff_id':'a'}}
        self.assertEqual(normalize_event(other),other)

    def test_accepts_all_five_independently_constructed_traces(self):
        for case_id in ('code-billing-handoff','model-technical-handoff','model-low-confidence-fallback','handoff-context-loss','handoff-receiver-unavailable'):
            c,r,e=valid_case(case_id)
            verifier.assert_case_behavior(r,e,c,'/trace.jsonl')

    def test_rejects_result_binding_and_sequence_mutations(self):
        c,r,e=valid_case()
        for key,value in [('case_id','wrong'),('router_mode','code'),('trace_path','wrong'),('run_id','wrong'),('specialist_invoked',False),('selected_route','billing'),('fallback_applied',False)]:
            with self.subTest(key=key),self.assertRaises(AssertionError): verifier.assert_case_behavior({**r,key:value},e,c,'/trace.jsonl')
        for mutation in ('run','sequence','terminal','handoff','sender','context','confidence','source','id'):
            bad=deepcopy(e)
            if mutation=='run': bad[1]['run_id']='wrong'
            if mutation=='sequence': bad[1]['sequence']=7
            if mutation=='terminal': bad.append(deepcopy(bad[-1]))
            if mutation=='handoff': bad[-2]['type']='handoff.rejected'
            if mutation=='sender': next(x for x in bad if x['type']=='handoff.requested')['data']['sender_intent']['route']='general'
            if mutation=='context': next(x for x in bad if x['type']=='handoff.requested')['data']['receiver_input']['prompt']='secret'
            if mutation=='confidence': next(x for x in bad if x['type']=='model.completed')['data']['decision']['confidence']=.92
            if mutation=='source': bad[1]['source']='typescript'
            if mutation=='id': bad[-2]['data']['handoff_id']='different'
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError): verifier.assert_case_behavior(r,bad,c,'/trace.jsonl')

    def test_rejects_model_in_code_and_acceptance_on_rejection(self):
        c,r,e=valid_case('code-billing-handoff')
        bad=deepcopy(e);bad.insert(2,{**bad[1],'type':'model.requested'})
        with self.assertRaises(AssertionError): verifier.assert_case_behavior(r,bad,c,'/trace.jsonl')
        for case_id in ('handoff-context-loss','handoff-receiver-unavailable'):
            c,r,e=valid_case(case_id)
            bad=deepcopy(e);bad[-2]['type']='handoff.accepted'
            with self.assertRaises(AssertionError): verifier.assert_case_behavior(r,bad,c,'/trace.jsonl')
            with self.assertRaises(AssertionError): verifier.assert_case_behavior({**r,'specialist_invoked':True},e,c,'/trace.jsonl')

    def test_evidence_requires_clean_same_revision_and_clears_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'verification-evidence.json'
            with patch.object(verifier,'assert_clean_worktree'),patch.object(verifier,'_revision',return_value='same'):
                verifier.publish_evidence({'revision':'same'},'same',target)
            self.assertEqual(json.loads(target.read_text())['revision'],'same')
            with patch.object(verifier,'assert_clean_worktree',side_effect=RuntimeError('dirty')):
                with self.assertRaises(RuntimeError): verifier.publish_evidence({},'same',target)
            with patch.object(verifier,'assert_clean_worktree'),patch.object(verifier,'_revision',return_value='moved'):
                with self.assertRaises(RuntimeError): verifier.publish_evidence({},'same',target)
            verifier.clear_previous_evidence(Path(directory))
            self.assertFalse(target.exists())
