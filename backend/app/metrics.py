from prometheus_client import Counter

# Business metrics: these are what make the Grafana dashboard tell a story about the
# application itself instead of only about the infrastructure underneath it.
BOOKING_OPERATIONS = Counter(
    "campusslot_bookings_total",
    "Booking operations that changed state.",
    ["action"],  # created | updated | deleted
)

BOOKING_CONFLICTS = Counter(
    "campusslot_booking_conflicts_total",
    "Overlapping booking requests that were rejected with 409.",
    ["layer"],  # application | database
)
