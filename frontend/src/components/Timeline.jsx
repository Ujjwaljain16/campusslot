import { blockPosition, formatRange, hourLabels } from "../lib/time";

export default function Timeline({
  rooms,
  bookings,
  stats,
  day,
  openHour,
  closeHour,
  tzOffset,
  onBookRoom,
  onSlotClick,
  onEditBooking,
}) {
  const labels = hourLabels(openHour, closeHour);
  const utilisation = new Map((stats?.rooms ?? []).map((room) => [room.room_id, room.utilisation_pct]));

  const bookingsFor = (roomId) => bookings.filter((booking) => booking.room_id === roomId);

  function handleTrackClick(event, room) {
    const rect = event.currentTarget.getBoundingClientRect();
    const fraction = (event.clientX - rect.left) / rect.width;
    const hour = openHour + Math.floor(fraction * (closeHour - openHour));
    onSlotClick(room, Math.min(Math.max(hour, openHour), closeHour - 1));
  }

  return (
    <section className="timeline" aria-label="Room schedule">
      <div className="timeline-head" aria-hidden="true">
        <div className="room-col" />
        <div className="hours" style={{ gridTemplateColumns: `repeat(${labels.length}, 1fr)` }}>
          {labels.map((label) => (
            <span key={label}>{label}</span>
          ))}
        </div>
      </div>

      {rooms.map((room) => {
        const roomBookings = bookingsFor(room.id);
        return (
          <div className="room-row" key={room.id}>
            <div className="room-col">
              <div>
                <strong>{room.name}</strong>
                <span className="room-meta">
                  {room.building} / {room.capacity} seats
                </span>
                {utilisation.has(room.id) && (
                  <span className="room-util" title="Share of opening hours that are booked">
                    {utilisation.get(room.id)}% booked
                  </span>
                )}
              </div>
              <button type="button" className="btn btn-small" onClick={() => onBookRoom(room)}>
                Book
              </button>
            </div>

            <div
              className="track"
              role="group"
              aria-label={`${room.name} schedule`}
              onClick={(event) => handleTrackClick(event, room)}
              style={{ "--slots": labels.length }}
            >
              {roomBookings.map((booking) => {
                const position = blockPosition(booking, day, openHour, closeHour, tzOffset);
                if (!position) return null;
                return (
                  <button
                    type="button"
                    key={booking.id}
                    className={`block${position.clippedStart ? " clip-start" : ""}${position.clippedEnd ? " clip-end" : ""}`}
                    style={{ left: `${position.leftPct}%`, width: `${position.widthPct}%` }}
                    title={`${booking.purpose} (${booking.booked_by})`}
                    onClick={(event) => {
                      event.stopPropagation();
                      onEditBooking(booking);
                    }}
                  >
                    <span className="block-time">{formatRange(booking.start_time, booking.end_time, tzOffset)}</span>
                    <span className="block-purpose">{booking.purpose}</span>
                  </button>
                );
              })}
            </div>

            <ul className="booking-list" aria-label={`${room.name} bookings`}>
              {roomBookings.length === 0 && <li className="booking-empty">Free all day</li>}
              {roomBookings.map((booking) => (
                <li key={booking.id}>
                  <button type="button" className="list-booking" onClick={() => onEditBooking(booking)}>
                    <strong>{formatRange(booking.start_time, booking.end_time, tzOffset)}</strong>
                    <span>
                      {booking.purpose} ({booking.booked_by})
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}
