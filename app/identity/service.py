from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations

import sqlalchemy as sa
from sqlalchemy.orm import Session, selectinload

from app.identity.rules import (
    NAME_SIMILARITY_THRESHOLD,
    RULE_NAME_CITY_MATCH,
    RULE_PHONE_EMAIL_EXACT,
    RULE_PHONE_NAME_SIMILAR,
    RULE_STRENGTH,
    STATUS_AUTO,
    STATUS_POSSIBLE_PENDING,
    STRENGTH_ORDER,
    name_similarity,
)
from app.ingestion.normalizers import normalize_key
from app.models import (
    Conversation,
    IdentityCluster,
    IdentityMember,
    Lead,
    PipelineRun,
)


def _build_edges(leads: list[dict]) -> tuple[list[dict], int]:
    by_phone: dict[tuple, list[dict]] = defaultdict(list)
    by_name_city: dict[tuple, list[dict]] = defaultdict(list)

    for lead in leads:
        if lead["phone_normalized"]:
            by_phone[(lead["company_id"], lead["phone_normalized"])].append(lead)
        name_key = normalize_key(lead["customer_name"])
        if name_key and lead["city_normalized"]:
            by_name_city[(lead["company_id"], name_key, lead["city_normalized"])].append(lead)

    edges: dict[frozenset, dict] = {}
    discarded = 0

    def add_edge(lead_a: dict, lead_b: dict, rule: str, evidence: dict) -> None:
        key = frozenset((lead_a["lead_id"], lead_b["lead_id"]))
        current = edges.get(key)
        if current is None or STRENGTH_ORDER[RULE_STRENGTH[rule]] < STRENGTH_ORDER[
            RULE_STRENGTH[current["rule"]]
        ]:
            edges[key] = {
                "a": lead_a["lead_id"],
                "b": lead_b["lead_id"],
                "rule": rule,
                "strength": RULE_STRENGTH[rule],
                "evidence": evidence,
            }

    for group in by_phone.values():
        for lead_a, lead_b in combinations(group, 2):
            same_email = bool(lead_a["email_normalized"]) and (
                lead_a["email_normalized"] == lead_b["email_normalized"]
            )
            similarity = name_similarity(lead_a["customer_name"], lead_b["customer_name"])
            if same_email:
                add_edge(
                    lead_a,
                    lead_b,
                    RULE_PHONE_EMAIL_EXACT,
                    {
                        "rule": RULE_PHONE_EMAIL_EXACT,
                        "phone_match": True,
                        "email_match": True,
                        "name_similarity": None,
                    },
                )
            elif similarity >= NAME_SIMILARITY_THRESHOLD:
                add_edge(
                    lead_a,
                    lead_b,
                    RULE_PHONE_NAME_SIMILAR,
                    {
                        "rule": RULE_PHONE_NAME_SIMILAR,
                        "phone_match": True,
                        "email_match": False,
                        "name_similarity": round(similarity, 4),
                    },
                )
            else:
                discarded += 1

    for group in by_name_city.values():
        for lead_a, lead_b in combinations(group, 2):
            key = frozenset((lead_a["lead_id"], lead_b["lead_id"]))
            if key in edges:
                continue
            add_edge(
                lead_a,
                lead_b,
                RULE_NAME_CITY_MATCH,
                {
                    "rule": RULE_NAME_CITY_MATCH,
                    "name_match": True,
                    "city_match": True,
                    "name_similarity": 1.0,
                },
            )

    return list(edges.values()), discarded


def _components(edges: list[dict]) -> list[set[str]]:
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(node_a: str, node_b: str) -> None:
        root_a, root_b = find(node_a), find(node_b)
        if root_a != root_b:
            parent[root_b] = root_a

    for edge in edges:
        union(edge["a"], edge["b"])

    grouped: dict[str, set[str]] = defaultdict(set)
    for node in parent:
        grouped[find(node)].add(node)
    return [component for component in grouped.values() if len(component) >= 2]


def _best_rule_by_lead(edges: list[dict]) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for edge in edges:
        for lead_id, other_id in ((edge["a"], edge["b"]), (edge["b"], edge["a"])):
            current = best.get(lead_id)
            if current is None or STRENGTH_ORDER[edge["strength"]] < STRENGTH_ORDER[
                current["strength"]
            ]:
                evidence = dict(edge["evidence"])
                evidence["related_lead_id"] = other_id
                best[lead_id] = {
                    "rule": edge["rule"],
                    "strength": edge["strength"],
                    "evidence": evidence,
                }
    return best


def _conversation_stats(session: Session) -> dict:
    with_lead = session.scalar(
        sa.select(sa.func.count())
        .select_from(Conversation)
        .where(Conversation.lead_id.is_not(None))
    )
    orphan = session.scalar(
        sa.select(sa.func.count())
        .select_from(Conversation)
        .where(Conversation.lead_id.is_(None))
    )
    multiple_subquery = (
        sa.select(Conversation.lead_id)
        .where(Conversation.lead_id.is_not(None))
        .group_by(Conversation.lead_id)
        .having(sa.func.count() > 1)
        .subquery()
    )
    multiple = session.scalar(
        sa.select(sa.func.count()).select_from(multiple_subquery)
    )
    total = session.scalar(sa.select(sa.func.count()).select_from(Conversation))
    return {
        "conversations_total": total,
        "conversations_with_lead": with_lead,
        "conversations_orphan": orphan,
        "leads_with_multiple_conversations": multiple,
    }


def _compute_identity(session: Session) -> dict:
    rows = session.execute(
        sa.select(
            Lead.lead_id,
            Lead.company_id,
            Lead.customer_name,
            Lead.phone_normalized,
            Lead.email_normalized,
            Lead.city_normalized,
        ).where(Lead.is_current.is_(True))
    ).all()
    leads = [dict(row._mapping) for row in rows]
    leads_by_id = {lead["lead_id"]: lead for lead in leads}

    edges, discarded = _build_edges(leads)
    components = _components(edges)
    best_by_lead = _best_rule_by_lead(edges)

    existing = list(
        session.scalars(
            sa.select(IdentityCluster).options(selectinload(IdentityCluster.members))
        ).all()
    )
    cluster_members = {
        cluster.cluster_id: {member.lead_id: member for member in cluster.members}
        for cluster in existing
    }

    clusters_created = 0
    clusters_reused = 0
    members_created = 0
    members_updated = 0
    members_unchanged = 0
    relations_by_rule = {
        RULE_PHONE_EMAIL_EXACT: 0,
        RULE_PHONE_NAME_SIMILAR: 0,
        RULE_NAME_CITY_MATCH: 0,
    }
    for edge in edges:
        relations_by_rule[edge["rule"]] += 1

    for component in components:
        company_id = leads_by_id[next(iter(component))]["company_id"]
        candidates = [
            (cluster, set(cluster_members[cluster.cluster_id]) & component)
            for cluster in existing
            if cluster.company_id == company_id
            and set(cluster_members[cluster.cluster_id]) & component
        ]

        if candidates:
            target, _ = max(candidates, key=lambda item: (len(item[1]), -item[0].cluster_id))
            clusters_reused += 1
            for other, _ in candidates:
                if other is target:
                    continue
                for lead_id, member in list(cluster_members[other.cluster_id].items()):
                    if lead_id in cluster_members[target.cluster_id]:
                        session.delete(member)
                    else:
                        member.cluster_id = target.cluster_id
                        cluster_members[target.cluster_id][lead_id] = member
                cluster_members.pop(other.cluster_id, None)
                session.delete(other)
                existing.remove(other)
        else:
            target = IdentityCluster(
                company_id=company_id,
                canonical_lead_id=min(component),
                status=STATUS_POSSIBLE_PENDING,
                match_strength="weak",
                matched_rules=[],
            )
            session.add(target)
            session.flush()
            cluster_members[target.cluster_id] = {}
            existing.append(target)
            clusters_created += 1

        component_edges = [
            edge for edge in edges if edge["a"] in component and edge["b"] in component
        ]
        strengths = {edge["strength"] for edge in component_edges}
        canonical = min(component)
        target.canonical_lead_id = canonical
        target.match_strength = min(strengths, key=lambda value: STRENGTH_ORDER[value])
        target.status = STATUS_AUTO if strengths == {"strong"} else STATUS_POSSIBLE_PENDING
        target.matched_rules = sorted({edge["rule"] for edge in component_edges})

        for lead_id in sorted(component):
            info = best_by_lead[lead_id]
            role = "canonical" if lead_id == canonical else "member"
            current_member = cluster_members[target.cluster_id].get(lead_id)
            if current_member is None:
                session.add(
                    IdentityMember(
                        cluster_id=target.cluster_id,
                        lead_id=lead_id,
                        role=role,
                        rule_id=info["rule"],
                        match_strength=info["strength"],
                        evidence=info["evidence"],
                    )
                )
                members_created += 1
            elif (
                current_member.role,
                current_member.rule_id,
                current_member.match_strength,
                current_member.evidence,
            ) != (role, info["rule"], info["strength"], info["evidence"]):
                current_member.role = role
                current_member.rule_id = info["rule"]
                current_member.match_strength = info["strength"]
                current_member.evidence = info["evidence"]
                members_updated += 1
            else:
                members_unchanged += 1

    size_distribution: dict[str, int] = defaultdict(int)
    for component in components:
        size_distribution[str(len(component))] += 1

    session.flush()

    report = {
        "leads_evaluated": len(leads),
        "clusters_created": clusters_created,
        "clusters_reused": clusters_reused,
        "clusters_total": session.scalar(
            sa.select(sa.func.count()).select_from(IdentityCluster)
        ),
        "members_created": members_created,
        "members_updated": members_updated,
        "members_unchanged": members_unchanged,
        "members_total": session.scalar(
            sa.select(sa.func.count()).select_from(IdentityMember)
        ),
        "relations_by_rule": relations_by_rule,
        "relations_discarded": discarded,
        "cluster_size_distribution": dict(sorted(size_distribution.items())),
    }
    report.update(_conversation_stats(session))
    return report


def run_identity(session: Session, trigger: str = "identity") -> dict:
    run = PipelineRun(trigger=trigger, status="running", source_hashes={})
    session.add(run)
    session.flush()

    failure: Exception | None = None
    steps: dict | None = None
    try:
        with session.begin_nested():
            steps = _compute_identity(session)
    except Exception as exc:  # noqa: BLE001
        failure = exc

    run.finished_at = datetime.now(timezone.utc)
    if failure is None:
        run.status = "completed"
        run.steps = steps
    else:
        run.status = "failed"
        run.error = f"{type(failure).__name__}: {failure}"
    session.commit()

    if failure is not None:
        raise failure

    return {
        "run_id": run.run_id,
        "trigger": run.trigger,
        "status": run.status,
        "steps": steps,
    }
