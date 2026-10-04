import os
import uuid
from datetime import datetime, timezone, timedelta
import httpx
from .db import Session, Record, records, put, now, settings

def dispatch(dry_run=False):
    """Persistent retry keys keep LINE retries idempotent; failed messages remain queued."""
    token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'); recipient=os.getenv('LINE_RECIPIENT_USER_ID')
    with Session.begin() as s:
        active=settings(s)['notifications'].get('enabled',False)
        alerts=records(s,'alert')
        report=[]
        for alert in alerts:
            if alert['status']=='sent': continue
            if alert.get('next_retry_at') and datetime.fromisoformat(alert['next_retry_at'])>datetime.now(timezone.utc): continue
            if dry_run or not active or not token or not recipient:
                report.append({'key':alert['key'],'status':'dry_run' if dry_run else 'not_configured','text':alert['text']}); continue
            retry_key=alert.get('retry_key') or str(uuid.uuid4())
            payload={k:v for k,v in alert.items() if k not in ('key','date')}
            payload['retry_key']=retry_key
            try:
                r=httpx.post('https://api.line.me/v2/bot/message/push',headers={'Authorization':'Bearer '+token,'X-Line-Retry-Key':retry_key},json={'to':recipient,'messages':[{'type':'text','text':alert['text']}]},timeout=20)
                if r.status_code==409 and r.headers.get('x-line-accepted-request-id') or r.is_success:
                    payload.update({'status':'sent','sent_at':now()})
                else:
                    raise RuntimeError('LINE HTTP '+str(r.status_code))
            except Exception as exc:
                attempts=alert.get('attempts',0)+1
                payload.update({'status':'failed','attempts':attempts,'last_error':str(exc),'next_retry_at':(datetime.now(timezone.utc)+timedelta(minutes=min(2**attempts,120))).isoformat()})
            put(s,'alert',alert['key'],payload,alert['date'])
            report.append({'key':alert['key'],'status':payload['status']})
        return report
