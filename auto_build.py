import sys
sys.stdout.reconfigure(line_buffering=True)

import httpx, json, time

BASE = 'http://127.0.0.1:8765'
client = httpx.Client(timeout=30)

def api(path, method='GET', data=None):
    url = BASE + path
    if method == 'GET':
        r = client.get(url)
    elif method == 'POST':
        r = client.post(url, json=data)
    r.raise_for_status()
    return r.json()

# 1. Create job
print('1. Creating job...')
result = api('/api/jobs', 'POST', {'type': 'github_hotlist'})
job = result['job']
job_id = job['id']
print(f'   Job created: {job_id}')

# 2. Start candidates collection
print('2. Collecting candidates...')
result = api(f'/api/jobs/{job_id}/candidates', 'POST')
print(f'   Started: {result.get("started")}')

# 3. Wait for candidates to be ready
print('3. Waiting for candidates...')
while True:
    time.sleep(3)
    detail = api(f'/api/jobs/{job_id}')
    job = detail['job']
    stage = job.get('stage', '')
    status = job.get('status', '')
    print(f'   Stage: {stage}, Status: {status}')
    if stage == 'awaiting_project_confirmation':
        break
    if status == 'failed':
        print('   FAILED!')
        exit(1)

# 4. Auto-select candidates (select first few)
print('4. Selecting candidates...')
candidates = detail.get('candidates', [])
selected = [{'full_name': c['full_name']} for c in candidates[:5]]
print(f'   Selecting: {[s["full_name"] for s in selected]}')
result = api(f'/api/jobs/{job_id}/selection', 'POST', {'items': selected})
print(f'   Selected {len(selected)} candidates')

# 5. Wait for script to be ready
print('5. Waiting for script generation...')
while True:
    time.sleep(3)
    detail = api(f'/api/jobs/{job_id}')
    job = detail['job']
    stage = job.get('stage', '')
    status = job.get('status', '')
    print(f'   Stage: {stage}, Status: {status}')
    if stage == 'awaiting_script_confirmation':
        break
    if status == 'failed':
        print('   FAILED!')
        exit(1)

# 6. Confirm script (use existing segments, ignore quality risk for auto-build)
print('6. Confirming script...')
segments = detail.get('segments', [])
segment_payload = [{'id': s['id'], 'label': s.get('label', ''), 'text': s.get('text', s.get('narration', ''))} for s in segments]
result = api(f'/api/jobs/{job_id}/script', 'POST', {'segments': segment_payload, 'ignore_quality_risk': True})
print(f'   Script confirmed, status={result["job"]["status"]}, stage={result["job"]["stage"]}')

# 7. Wait for plan preparation stage
print('7. Waiting for plan preparation stage...')
while True:
    time.sleep(3)
    detail = api(f'/api/jobs/{job_id}')
    job = detail['job']
    stage = job.get('stage', '')
    status = job.get('status', '')
    print(f'   Stage: {stage}, Status: {status}')
    # After confirming script with ignore_quality_risk, status should become awaiting_render
    if stage == 'preparing_plan' and status == 'awaiting_render':
        break
    if stage == 'preparing_plan' and status in ('ready_to_render', 'failed'):
        break
    if status == 'failed':
        print(f'   FAILED! Error: {job.get("error", "")}')
        exit(1)
    # If still awaiting_script_confirmation after script confirm, something went wrong
    if stage == 'awaiting_script_confirmation' and status == 'awaiting_input':
        print('   Script quality check failed, retrying...')
        # Retry with force ignore
        result = api(f'/api/jobs/{job_id}/script', 'POST', {'segments': segment_payload, 'ignore_quality_risk': True})
        time.sleep(2)

# 8. Prepare plan
print('8. Preparing plan...')
result = api(f'/api/jobs/{job_id}/prepare-plan', 'POST')
print(f'   Plan prepared')

# 8.5 Wait for plan preparation to complete and validate if needed
print('8.5 Waiting for plan preparation...')
while True:
    time.sleep(3)
    detail = api(f'/api/jobs/{job_id}')
    job = detail['job']
    stage = job.get('stage', '')
    status = job.get('status', '')
    print(f'   Stage: {stage}, Status: {status}')
    if status == 'ready_to_render':
        print('   Plan ready for rendering')
        break
    if status == 'awaiting_validation':
        print('   Validating plan...')
        result = api(f'/api/jobs/{job_id}/validate-plan', 'POST')
        print(f'   Plan validated, status={result["job"]["status"]}')
        break
    if status == 'failed':
        print(f'   FAILED! Error: {job.get("error", "")}')
        exit(1)
    if stage not in ('preparing_plan',):
        print(f'   Unexpected stage: {stage}, waiting...')

# Wait for rendering to complete
print('9. Starting rendering...')
detail = api(f'/api/jobs/{job_id}')
job = detail['job']
status = job.get('status', '')
if status == 'ready_to_render':
    print('   Starting render-video...')
    result = api(f'/api/jobs/{job_id}/render-video', 'POST')
    print(f'   Render started')

print('10. Waiting for rendering to complete...')
while True:
    time.sleep(5)
    detail = api(f'/api/jobs/{job_id}')
    job = detail['job']
    stage = job.get('stage', '')
    status = job.get('status', '')
    progress = job.get('render_progress', {})
    print(f'   Stage: {stage}, Status: {status}, Progress: {progress}')
    if status in ('completed', 'failed'):
        break

print()
print('=== DONE ===')
print(f'Job ID: {job_id}')
print(f'Final Status: {job.get("status")}')