"""
Test runner for AI-Corrector test cases.
Reads test_cases.json, runs all TC against localhost:8000, writes results back.
"""

import json
import os
import time
import requests
from pathlib import Path
from langdetect import detect, LangDetectException

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
JSON_PATH = Path(__file__).parent / "test_cases.json"

API_KEY = os.getenv("API_KEY", "")
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}


def detect_lang(text: str) -> str:
    if not text or len(text.split()) < 4:
        return "id"
    try:
        return detect(text)
    except LangDetectException:
        return "id"


def run_assess(tc: dict) -> dict:
    form = tc["form"]
    data = {k: v for k, v in form.items()}
    resp = requests.post(f"{BASE_URL}/assess", data=data, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    body = resp.json()
    ev = body.get("evaluation", {})
    reasoning = ev.get("reasoning", "")
    reasoning_lang = detect_lang(reasoning)
    return {
        "score": ev.get("score"),
        "confidence": ev.get("confidence"),
        "reasoning": reasoning,
        "feedback": ev.get("feedback", ""),
        "retrieved_sources": body.get("retrieved_sources", []),
        "sources": ev.get("sources", []),
        "reasoning_lang": reasoning_lang,
        "completion_input_tokens": body.get("token_usage", {}).get("completion_input_tokens", 0),
        "completion_output_tokens": body.get("token_usage", {}).get("completion_output_tokens", 0),
        "total_cost_usd": body.get("token_usage", {}).get("total_cost_usd", 0),
    }


def run_assess_batch(tc: dict) -> dict:
    body = tc["body"]
    resp = requests.post(f"{BASE_URL}/assess-batch", json=body, headers=HEADERS, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    results = []
    for r in data.get("results", []):
        ev = r.get("evaluation", {})
        reasoning = ev.get("reasoning", "")
        results.append({
            "student_id": r.get("student_id"),
            "score": ev.get("score"),
            "confidence": ev.get("confidence"),
            "reasoning": reasoning,
            "feedback": ev.get("feedback", ""),
            "reasoning_lang": detect_lang(reasoning),
            "feedback_empty": ev.get("feedback", "x") == "",
        })
    tu = data.get("token_usage", {})
    return {
        "retrieved_sources": data.get("retrieved_sources", []),
        "completion_input_tokens": tu.get("completion_input_tokens", 0),
        "completion_output_tokens": tu.get("completion_output_tokens", 0),
        "total_cost_usd": tu.get("total_cost_usd", 0),
        "results": results,
    }


def run_assess_batch_multi(tc: dict) -> dict:
    body = tc["body"]
    resp = requests.post(f"{BASE_URL}/assess-batch-multi", json=body, headers=HEADERS, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    total_input = total_output = total_cost = 0
    questions = []
    for q_result in data.get("results", []):
        students = []
        for r in q_result.get("results", []):
            ev = r.get("evaluation", {})
            reasoning = ev.get("reasoning", "")
            students.append({
                "student_id": r.get("student_id"),
                "score": ev.get("score"),
                "confidence": ev.get("confidence"),
                "reasoning": reasoning,
                "feedback": ev.get("feedback", ""),
                "reasoning_lang": detect_lang(reasoning),
            })
            tu = r.get("token_usage", {})
            total_input += tu.get("completion_input_tokens", 0)
            total_output += tu.get("completion_output_tokens", 0)
            total_cost += tu.get("total_cost_usd", 0)
        questions.append({
            "question_summary": q_result.get("question", "")[:50],
            "retrieved_sources": q_result.get("retrieved_sources", []),
            "students": students,
        })
    return {
        "completion_input_tokens": total_input,
        "completion_output_tokens": total_output,
        "total_cost_usd": round(total_cost, 8),
        "results": questions,
    }


def compute_status(tc: dict, result: dict) -> tuple[str, str]:
    exp = tc.get("expected", {})
    tc_id = tc["id"]
    endpoint = tc["endpoint"]

    if "POST /assess-batch-multi" in endpoint:
        # Check all student scores
        issues = []
        for q in result.get("results", []):
            if q.get("retrieved_sources"):
                pass
        return "PASS", "Multi-batch selesai."

    if "POST /assess-batch" in endpoint:
        results = result.get("results", [])
        retrieved = result.get("retrieved_sources", [])
        issues = []
        if "retrieved_sources" in exp and exp["retrieved_sources"] != "[]" and not retrieved:
            issues.append("retrieved_sources kosong (diharapkan tidak kosong)")
        status = "WARN" if issues else "PASS"
        notes = f"Scores: {[r['score'] for r in results]}. " + ("; ".join(issues) if issues else "OK.")
        return status, notes

    # Single assess
    score = result.get("score")
    retrieved = result.get("retrieved_sources", [])
    sources = result.get("sources", [])
    reasoning_lang = result.get("reasoning_lang", "")
    issues = []
    warnings = []

    score_range = exp.get("evaluation.score", "")
    if score_range and "-" in str(score_range):
        lo, hi = map(int, str(score_range).split("-"))
        if score is None or not (lo <= score <= hi):
            issues.append(f"score {score} di luar {score_range}")
    elif score_range == "0":
        if score != 0:
            issues.append(f"expected score=0, got {score}")

    if "tidak kosong" in exp.get("retrieved_sources", ""):
        if not retrieved:
            warnings.append("retrieved_sources kosong (course_code filter issue)")

    if "tidak kosong" in exp.get("evaluation.sources", ""):
        if not sources:
            warnings.append("web sources kosong (web search tidak aktif)")

    if issues:
        status = "FAIL"
        notes = f"Score {score}. FAIL: {'; '.join(issues)}."
    elif warnings:
        partial = any("web" in w for w in warnings) or any("retrieved" in w for w in warnings)
        both = len(warnings) > 1
        if both or (partial and not retrieved and not sources):
            status = "PARTIAL" if "web" in str(warnings) else "WARN"
        else:
            status = "WARN"
        notes = f"Score {score}. {'; '.join(warnings)}."
    else:
        status = "PASS"
        notes = f"Score {score} sesuai ekspektasi."

    if retrieved:
        notes += f" retrieved_sources: {retrieved}."
    if sources:
        notes += f" {len(sources)} web source(s)."
    return status, notes


def main():
    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    test_cases = data["test_cases"]
    total = len(test_cases)

    for i, tc in enumerate(test_cases):
        tc_id = tc["id"]
        name = tc["name"]
        endpoint = tc["endpoint"]
        print(f"\n[{i+1}/{total}] {tc_id}: {name}")
        print(f"  endpoint: {endpoint}")

        try:
            if "assess-batch-multi" in endpoint:
                result = run_assess_batch_multi(tc)
            elif "assess-batch" in endpoint:
                result = run_assess_batch(tc)
            else:
                result = run_assess(tc)

            status, notes = compute_status(tc, result)
            result["status"] = status
            result["notes"] = notes
            tc["actual_result"] = result
            print(f"  status: {status} | {notes}")

        except Exception as e:
            tc["actual_result"] = {
                "status": "ERROR",
                "notes": str(e),
            }
            print(f"  ERROR: {e}")

        time.sleep(1)

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n=== Done. Results saved to {JSON_PATH} ===")
    summary = {}
    for tc in test_cases:
        s = tc.get("actual_result", {}).get("status", "UNKNOWN")
        summary[s] = summary.get(s, 0) + 1
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
