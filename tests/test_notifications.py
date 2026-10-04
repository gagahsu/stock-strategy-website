from datetime import datetime,timezone
from backend.db import Session,put,get,Record
from backend.notifications import dispatch
import httpx
import pytest

def test_missing_line_credentials_keep_alert_pending(monkeypatch):
    monkeypatch.delenv('LINE_CHANNEL_ACCESS_TOKEN',raising=False)
    monkeypatch.delenv('LINE_RECIPIENT_USER_ID',raising=False)
    key='unit-test-alert'
    with Session.begin() as s:put(s,'alert',key,{'text':'測試通知','status':'pending','attempts':0},'2024-01-01')
    try:
        result=dispatch()
        assert next(x for x in result if x['key']==key)['status']=='not_configured'
        with Session() as s:assert get(s,'alert',key,'2024-01-01')['status']=='pending'
    finally:
        with Session.begin() as s:s.delete(s.get(Record,('alert',key,'2024-01-01')))


@pytest.mark.parametrize('status,accepted,expected',[(200,False,'sent'),(409,True,'sent'),(409,False,'failed'),(500,False,'failed')])
def test_line_delivery_retry_and_duplicate_acknowledgment(monkeypatch,status,accepted,expected):
    from backend.db import records as stored_records
    key='unit-test-line-delivery'
    monkeypatch.setenv('LINE_CHANNEL_ACCESS_TOKEN','mock-token')
    monkeypatch.setenv('LINE_RECIPIENT_USER_ID','mock-recipient')
    monkeypatch.setattr('backend.notifications.settings',lambda s:{'notifications':{'enabled':True}})
    monkeypatch.setattr('backend.notifications.records',lambda s,k:[r for r in stored_records(s,k) if r['key']==key])
    calls=[]
    def post(url,**kwargs):
        calls.append(kwargs['headers']['X-Line-Retry-Key'])
        return httpx.Response(status,headers={'x-line-accepted-request-id':'mock-id'} if accepted else {})
    monkeypatch.setattr('backend.notifications.httpx.post',post)
    with Session.begin() as s:put(s,'alert',key,{'text':'模擬通知','status':'pending','attempts':0},'2024-01-01')
    try:
        assert dispatch()[0]['status']==expected
        assert dispatch()==[]  # Sent messages and future retries are both skipped.
        if expected=='failed':
            with Session.begin() as s:
                item=get(s,'alert',key,'2024-01-01');item['next_retry_at']='2000-01-01T00:00:00+00:00'
                put(s,'alert',key,item,'2024-01-01')
            dispatch()
            assert len(calls)==2 and calls[0]==calls[1]
        else:assert len(calls)==1
    finally:
        with Session.begin() as s:s.delete(s.get(Record,('alert',key,'2024-01-01')))
