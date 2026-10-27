"""Notify once when a newly refreshed schedule introduces a conflict."""
import json
from datetime import datetime
from uuid import uuid4
from sqlalchemy import text


def mark_checked_conflicts(connection, subject_kind, subject_id, issues, default_person=None):
    resources=set()
    for issue in issues:
        if issue['kind']!='source_conflict': continue
        resource_kind=issue.get('resource_kind','person')
        resource_id=issue.get('resource_id',default_person)
        if resource_id: resources.add((resource_kind,resource_id))
    for kind, resource_id in resources:
        connection.execute(text("""INSERT INTO zapara.schedule_alerts(subject_kind,subject_id,resource_kind,resource_id,active)
            VALUES (:subject_kind,:subject_id,:kind,:resource_id,true)
            ON CONFLICT(subject_kind,subject_id,resource_kind,resource_id) DO UPDATE SET active=true,updated_at=now()"""),
            {'subject_kind':subject_kind,'subject_id':subject_id,'kind':kind,'resource_id':resource_id})


def overlapping(payload,day,start,end):
    for event in payload:
        if event['date'].replace('.','-')!=day.isoformat(): continue
        if datetime.strptime(event['beginLesson'],'%H:%M').time()<end and datetime.strptime(event['endLesson'],'%H:%M').time()>start:
            return True
    return False


def update_schedule_alerts(connection,job,payload):
    kind,resource_id=job['entity_kind'],job['external_id']
    if kind not in ('person','group','auditorium'): return
    params={'kind':kind,'resource_id':resource_id,'start':job['range_start'],'end':job['range_end']}
    slots=connection.execute(text("""SELECT sl.id,sl.event_date,sl.slot_number,sl.starts_at,sl.ends_at,p.id AS plan_id,p.owner_id
        FROM zapara.slot_resources r JOIN zapara.plan_slots sl ON sl.id=r.slot_id JOIN zapara.plans p ON p.id=sl.plan_id
        WHERE r.kind=:kind AND r.external_id=:resource_id AND sl.status='confirmed' AND p.status<>'archived'
          AND sl.event_date BETWEEN :start AND :end
          AND ((sl.event_date+sl.ends_at) AT TIME ZONE sl.timezone)>now()"""),params).mappings().all()
    subjects=[('slot',row) for row in slots]
    if kind=='person':
        substitutions=connection.execute(text("""SELECT s.id,sl.event_date,sl.slot_number,sl.starts_at,sl.ends_at,p.id AS plan_id,p.owner_id,
            (SELECT user_id FROM zapara.teacher_links WHERE person_id=s.substitute_person_id) AS substitute_user_id
            FROM zapara.substitutions s JOIN zapara.plan_slots sl ON sl.id=s.slot_id JOIN zapara.plans p ON p.id=sl.plan_id
            WHERE s.substitute_person_id=:resource_id AND s.status='confirmed' AND p.status<>'archived'
              AND sl.event_date BETWEEN :start AND :end
          AND ((sl.event_date+sl.ends_at) AT TIME ZONE sl.timezone)>now()"""),params).mappings().all()
        subjects += [('substitution',row) for row in substitutions]
    for subject_kind,subject in subjects:
        conflict=overlapping(payload,subject['event_date'],subject['starts_at'],subject['ends_at'])
        key={'subject_kind':subject_kind,'subject_id':subject['id'],'kind':kind,'resource_id':resource_id}
        old=connection.execute(text("""SELECT active FROM zapara.schedule_alerts WHERE subject_kind=:subject_kind
            AND subject_id=:subject_id AND resource_kind=:kind AND resource_id=:resource_id FOR UPDATE"""),key).scalar_one_or_none()
        connection.execute(text("""INSERT INTO zapara.schedule_alerts(subject_kind,subject_id,resource_kind,resource_id,active)
            VALUES (:subject_kind,:subject_id,:kind,:resource_id,:active)
            ON CONFLICT(subject_kind,subject_id,resource_kind,resource_id) DO UPDATE SET active=excluded.active,updated_at=now()"""),{**key,'active':conflict})
        if conflict and not old:
            recipients={subject['owner_id']}
            if subject_kind=='substitution' and subject['substitute_user_id']: recipients.add(subject['substitute_user_id'])
            details=json.dumps({'event_date':subject['event_date'].isoformat(),'slot_number':subject['slot_number'],'resource_kind':kind})
            for recipient in recipients:
                connection.execute(text("""INSERT INTO zapara.notifications(id,user_id,plan_id,kind,payload)
                    VALUES (:id,:user,:plan,'schedule_conflict',CAST(:payload AS jsonb))"""),
                    {'id':uuid4(),'user':recipient,'plan':subject['plan_id'],'payload':details})
