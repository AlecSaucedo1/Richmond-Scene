from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

BEATS={"businesses":"Business & storefronts","permits":"Development & housing","service_requests":"Streets & city services","police":"Public safety"}
ALIASES={"Bayview Hunters Point":["bayview","hunters point","shipyard"],"Financial District/South Beach":["financial district","fidi","south beach","downtown san francisco"],"Castro/Upper Market":["castro","upper market"],"Oceanview/Merced/Ingleside":["oceanview","merced","ingleside"],"South of Market":["south of market","soma"],"Sunset/Parkside":["sunset","parkside"],"Potrero Hill":["potrero hill","dogpatch","power station"],"Mission":["mission district","the mission","mission street"],"Chinatown":["chinatown","portsmouth square"],"Western Addition":["western addition","fillmore"]}

def norm(v): return re.sub(r"[^a-z0-9]+"," ",str(v or "").lower()).strip()

def published(item):
    try:
        d=datetime.fromisoformat(str(item.get("published") or "").replace("Z","+00:00")); return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception: return datetime.now(timezone.utc)

def recent(item,now,days=40): return published(item)>=now-timedelta(days=days)

def aliases(name):
    vals=[name.lower(),*ALIASES.get(name,[])]
    if "/" in name: vals += [x.strip().lower() for x in name.split("/") if len(x.strip())>3]
    return list(dict.fromkeys(vals))

def record_terms(e):
    n=e.get("notable",{}); out=[]
    out += [norm(x.get("title")) for x in n.get("businesses",[])[:3] if len(norm(x.get("title")))>4]
    out += [norm(x.get("address")) for x in n.get("permits",[])[:3] if len(norm(x.get("address")))>4]
    return out

def coverage_for(e,items,now):
    out=[]; hood=e["name"]; lead=(e.get("lead") or {}).get("source")
    for item in items:
        if not recent(item,now): continue
        body=norm((item.get("title") or "")+" "+(item.get("summary") or ""))
        explicit=hood in (item.get("neighborhoods") or [])
        hood_hit=explicit or any(norm(a) in body for a in aliases(hood))
        rec_hit=any(t in body for t in record_terms(e))
        if not hood_hit and not rec_hit: continue
        score=(10 if explicit else 7)+(12 if rec_hit else 0)+(5 if item.get("beat")==lead else 1)
        reason="Matches a named filing or location" if rec_hit else "Names the neighborhood"
        if item.get("beat")==lead: reason += f" and this week's {BEATS.get(lead,'lead')} signal"
        out.append((score,published(item),{**item,"match_reason":reason}))
    out.sort(key=lambda x:(x[0],x[1]),reverse=True)
    return [x[2] for x in out[:3]]

def why_for(e,cov):
    lead=e.get("lead") or {}; key=lead.get("source"); m=e.get("metrics",{}).get(key,{})
    pct=m.get("pct_change"); direction="above" if pct is not None and pct>8 else ("below" if pct is not None and pct<-8 else "near")
    mag=f"{abs(pct):.0f}% " if pct is not None else ""
    if key=="businesses":
        h="Why the storefront numbers may be moving"; a=f"New business-location registrations are {mag}{direction} the neighborhood's recent weekly average. Registrations can reflect real openings, relocations, ownership changes or administrative filings, so the named storefronts matter more than the count alone."; w="Watch whether registrations keep appearing on the same commercial corridors; persistence is a stronger signal than a one-week burst."
    elif key=="permits":
        housing=next((x for x in e.get("notable",{}).get("permits",[]) if (x.get("unit_delta") or 0)>0),None); h="Why development activity may be shifting"
        a=f"Permit activity is {mag}{direction} its recent average. " + (f"The mix includes a filing proposing {housing['unit_delta']} net new housing units, making the signal more meaningful than routine alterations." if housing else "Weekly permit counts are lumpy, so project scale, use changes and housing-unit changes are better clues to the development cycle than volume alone.")
        w="Watch for repeat filings, planning milestones and unit-count changes; those show whether activity is becoming a durable pipeline."
    elif key=="service_requests":
        h="Why 311 can move suddenly"; a=f"311 volume is {mag}{direction} its recent weekly average. The feed measures both conditions and residents' willingness to report them, so construction, city operations, a concentrated nuisance or a reporting campaign can move the number quickly."; w="Watch whether the same request type persists and clusters around a project, corridor or public-space change."
    else:
        h="Why the public-safety number needs context"; a=f"Reported incidents are {mag}{direction} the recent weekly average. At neighborhood scale, a few incidents or a change in reporting can materially shift a seven-day percentage, so the eight-week pulse and incident mix matter more than one headline number."; w="Watch whether the same incident category persists across multiple weeks before treating the move as a neighborhood trend."
    if cov: a += " Recent local reporting offers a possible explanation or backdrop below, but timing alone is not treated as proof of causation."
    return {"headline":h,"analysis":a,"watch":w,"coverage":cov}

def city_metric(snapshot,key):
    ms=[e.get("metrics",{}).get(key) for e in snapshot.get("editions",{}).values()]; ms=[m for m in ms if m]
    cur=sum(m.get("current",0) for m in ms); base=sum(float(m.get("baseline_week",0)) for m in ms); pct=((cur-base)/base*100) if base>=1 else None
    return {"current":cur,"baseline_week":round(base,1),"pct_change":round(pct,1) if pct is not None else None}

def top_hoods(snapshot,key):
    rows=[]
    for e in snapshot.get("editions",{}).values():
        m=e.get("metrics",{}).get(key)
        if not m: continue
        d=m.get("current",0)-float(m.get("baseline_week",0)); rows.append({"name":e["name"],"slug":e["slug"],"current":m.get("current",0),"delta":round(d,1),"pct_change":m.get("pct_change")})
    return sorted(rows,key=lambda x:abs(x["delta"]),reverse=True)[:4]

def city_theme(snapshot,key,items,now):
    m=city_metric(snapshot,key); pct=m.get("pct_change"); d="up" if pct is not None and pct>8 else ("down" if pct is not None and pct<-8 else "roughly flat"); top=top_hoods(snapshot,key); names=", ".join(x["name"] for x in top[:3]) or "several neighborhoods"
    why={"businesses":"Registrations mix real storefront momentum with administrative churn. Repeated corridor activity plus reporting on leases, grants, vacancies or foot traffic helps explain whether the change is durable.","permits":"Financing costs, zoning changes, project redesigns and office-to-housing efforts are shaping the development cycle. Unit-adding filings and large milestones matter more than raw permit volume.","service_requests":"311 reacts to construction, public-space work, enforcement and reporting behavior. Persistent category changes across several neighborhoods are stronger evidence than a one-week spike.","police":"Reported crime can move differently by category and neighborhood. Small weekly counts are volatile, so citywide direction and multi-week persistence provide the best context."}[key]
    headline={"businesses":f"Business registrations are {d}; {names} are moving the weekly total", "permits":f"Development filings are {d}, with the biggest shifts in {names}", "service_requests":f"311 activity is {d}; the largest deviations are in {names}", "police":f"Reported incidents are {d}; {names} show the largest departures from baseline"}[key]
    cov=[x for x in items if x.get("beat")==key and recent(x,now)]; cov.sort(key=published,reverse=True)
    return {"key":key,"label":BEATS[key],"headline":headline,"why":why,"metric":m,"neighborhoods":top,"coverage":cov[:3]}

def enrich_snapshot(snapshot,items,generated_at=None):
    now=generated_at or datetime.now(timezone.utc)
    for e in snapshot.get("editions",{}).values(): e["editorial"]=why_for(e,coverage_for(e,items,now))
    themes=[city_theme(snapshot,k,items,now) for k in ("businesses","permits","service_requests","police")]
    strongest=sorted(themes,key=lambda t:abs(t["metric"].get("pct_change") or 0)+min(t["metric"].get("current",0),200)/20,reverse=True)
    summary=(f"The strongest citywide public-record signal this week is {strongest[0]['label'].lower()}. The city page separates the raw movement from plausible explanations in recent reporting, then shows which neighborhoods are contributing most." if strongest else "The city page connects neighborhood signals with recent reporting to explain what may be driving the numbers.")
    cross=[]
    for e in snapshot.get("editions",{}).values():
        cov=e.get("editorial",{}).get("coverage",[])
        if cov and e.get("lead"): cross.append({"name":e["name"],"slug":e["slug"],"headline":e["lead"]["headline"],"section":e["lead"]["section"],"article":cov[0],"interest":e["lead"].get("interest",0)})
    cross.sort(key=lambda x:x["interest"],reverse=True)
    snapshot["city_analysis"]={"summary":summary,"themes":themes,"crossovers":cross[:12],"news_count":len([x for x in items if recent(x,now)])}
    snapshot["news_context"]={"updated_at":now.isoformat(),"items_considered":len(items)}
    return snapshot
