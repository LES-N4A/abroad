from datetime import date, datetime

from db import query
from services import cart_totals


def _parse(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def remaining_capacity(trip):
    return max(0.0, float(trip["capacity_kg"]) - float(trip["used_kg"]))


def score_trip(trip, cart, weight):
    """Return a 0-100 score, or None when the trip cannot carry this cart."""
    if trip["status"] != "verified":
        return None
    if remaining_capacity(trip) < weight:
        return None
    if trip["to_city"].lower() != cart["delivery_city"].lower():
        return None

    arrival = _parse(trip["arrival_date"])
    delivery = _parse(cart["delivery_date"])
    if arrival > delivery:
        return None
    if arrival < date.today():
        return None

    fill = float(trip["used_kg"]) / float(trip["capacity_kg"]) if trip["capacity_kg"] else 1
    days_buffer = (delivery - arrival).days
    # Fees are stored in millimes; 1 DT costs 2 points.
    score = 70 - ((trip["fee"] or 0) / 500) - (fill * 20) + min(days_buffer, 10)
    return round(max(0.0, min(100.0, score)), 1)


def eligible_trips(cart, traveler_id):
    """Trips owned by the traveler that can carry the cart, best first."""
    _, weight = cart_totals(cart["id"])
    trips = query(
        "SELECT * FROM trips WHERE traveler_id = ? AND status = 'verified'",
        (traveler_id,),
    )
    scored = []
    for trip in trips:
        score = score_trip(trip, cart, weight)
        if score is not None:
            scored.append({"trip": trip, "score": score, "remaining": remaining_capacity(trip)})
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored


def best_trip(cart, traveler_id):
    matches = eligible_trips(cart, traveler_id)
    return matches[0] if matches else None
