import { useEffect, useRef, useState } from "react";

import { ApiError, api } from "../lib/api";
import { formatRange, isoToLocalParts, localToIso, offsetForDay } from "../lib/time";

const BOOKED_BY_KEY = "campusslot.bookedBy";
const pad = (n) => String(n).padStart(2, "0");

function rememberedName() {
  try {
    return window.localStorage.getItem(BOOKED_BY_KEY) ?? "";
  } catch {
    return "";
  }
}

function describeFailure(error, date) {
  if (error instanceof ApiError && error.status === 409 && error.detail?.conflicting_booking) {
    const other = error.detail.conflicting_booking;
    const range = formatRange(other.start_time, other.end_time, offsetForDay(date));
    return `That time overlaps an existing booking (${range}) made by ${other.booked_by} for "${other.purpose}".`;
  }
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

export default function BookingDialog({ rooms, day, booking, roomId, startHour, onClose, onSaved }) {
  const dialogRef = useRef(null);
  const editing = Boolean(booking);

  const startParts = editing ? isoToLocalParts(booking.start_time, offsetForDay(day)) : null;
  const endParts = editing ? isoToLocalParts(booking.end_time, offsetForDay(day)) : null;
  const firstHour = startHour ?? 9;

  const [room, setRoom] = useState(String(booking?.room_id ?? roomId ?? rooms[0]?.id ?? ""));
  const [purpose, setPurpose] = useState(booking?.purpose ?? "");
  const [bookedBy, setBookedBy] = useState(booking?.booked_by ?? rememberedName());
  const [date, setDate] = useState(startParts?.date ?? day);
  const [start, setStart] = useState(startParts?.time ?? `${pad(firstHour)}:00`);
  const [end, setEnd] = useState(endParts?.time ?? `${pad(firstHour + 1)}:00`);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  function buildPayload() {
    const offset = offsetForDay(date);
    return {
      room_id: Number(room),
      purpose: purpose.trim(),
      booked_by: bookedBy.trim(),
      start_time: localToIso(date, start, offset),
      end_time: localToIso(date, end, offset),
    };
  }

  async function run(action, successMessage) {
    setBusy(true);
    setError(null);
    try {
      await action();
      onSaved(successMessage);
    } catch (failure) {
      setError(describeFailure(failure, date));
      setBusy(false);
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    if (end <= start) {
      setError("The end time must be after the start time.");
      return;
    }
    try {
      window.localStorage.setItem(BOOKED_BY_KEY, bookedBy.trim());
    } catch {
      /* storage can be unavailable in private windows; remembering the name is optional */
    }
    const payload = buildPayload();
    if (editing) {
      run(() => api.updateBooking(booking.id, { ...payload, status: "confirmed" }), "Booking updated");
    } else {
      run(() => api.createBooking(payload), "Booking confirmed");
    }
  }

  function handleCancelBooking() {
    run(() => api.updateBooking(booking.id, { ...buildPayload(), status: "cancelled" }), "Booking cancelled");
  }

  function handleDelete() {
    if (!window.confirm("Delete this booking permanently?")) return;
    run(() => api.deleteBooking(booking.id), "Booking deleted");
  }

  return (
    <dialog
      ref={dialogRef}
      className="dialog"
      aria-labelledby="dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === dialogRef.current) onClose();
      }}
    >
      <form onSubmit={handleSubmit} className="dialog-form">
        <h2 id="dialog-title">{editing ? "Edit booking" : "New booking"}</h2>

        <label>
          Room
          <select value={room} onChange={(event) => setRoom(event.target.value)} required>
            {rooms.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.building})
              </option>
            ))}
          </select>
        </label>

        <label>
          Purpose
          <input
            value={purpose}
            onChange={(event) => setPurpose(event.target.value)}
            maxLength={120}
            placeholder="For example: Operating Systems lab"
            required
          />
        </label>

        <label>
          Booked by
          <input
            value={bookedBy}
            onChange={(event) => setBookedBy(event.target.value)}
            maxLength={80}
            placeholder="Your name"
            required
          />
        </label>

        <div className="field-row">
          <label>
            Date
            <input type="date" value={date} onChange={(event) => setDate(event.target.value)} required />
          </label>
          <label>
            From
            <input type="time" step="900" value={start} onChange={(event) => setStart(event.target.value)} required />
          </label>
          <label>
            To
            <input type="time" step="900" value={end} onChange={(event) => setEnd(event.target.value)} required />
          </label>
        </div>

        <p className="form-error" role="alert" aria-live="assertive">
          {error}
        </p>

        <div className="dialog-actions">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? "Saving..." : editing ? "Save changes" : "Confirm booking"}
          </button>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Close
          </button>
          {editing && (
            <>
              <button type="button" className="btn btn-warn" onClick={handleCancelBooking} disabled={busy}>
                Cancel booking
              </button>
              <button type="button" className="btn btn-danger" onClick={handleDelete} disabled={busy}>
                Delete
              </button>
            </>
          )}
        </div>
      </form>
    </dialog>
  );
}
