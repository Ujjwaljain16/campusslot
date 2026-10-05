import { useCallback, useEffect, useMemo, useState } from "react";

import BookingDialog from "./components/BookingDialog";
import KpiCards from "./components/KpiCards";
import Timeline from "./components/Timeline";
import { api } from "./lib/api";
import { formatDayHeading, offsetForDay, shiftDay, todayString } from "./lib/time";

const POLL_MS = 30000;

export default function App() {
  const [day, setDay] = useState(todayString());
  const [info, setInfo] = useState(null);
  const [rooms, setRooms] = useState([]);
  const [bookings, setBookings] = useState([]);
  const [stats, setStats] = useState(null);
  const [phase, setPhase] = useState("loading"); // loading | ready
  const [error, setError] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [toast, setToast] = useState(null);

  const tzOffset = useMemo(() => offsetForDay(day), [day]);
  const isToday = day === todayString();
  const openHour = info?.day_open_hour ?? 8;
  const closeHour = info?.day_close_hour ?? 20;

  const load = useCallback(
    async (showSpinner) => {
      if (showSpinner) setPhase("loading");
      try {
        const [roomList, bookingList, statList] = await Promise.all([
          api.listRooms(),
          api.listBookings({ day, tzOffset }),
          api.stats({ day, tzOffset }),
        ]);
        setRooms(roomList);
        setBookings(bookingList);
        setStats(statList);
        setError(null);
      } catch (failure) {
        setError(failure.message);
      } finally {
        setPhase("ready");
      }
    },
    [day, tzOffset],
  );

  useEffect(() => {
    load(true);
  }, [load]);

  // Keep the schedule fresh when other people book from other browsers.
  useEffect(() => {
    const timer = setInterval(() => load(false), POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    api.info().then(setInfo).catch(() => {});
  }, []);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  function handleSaved(message) {
    setDialog(null);
    setToast(message);
    load(false);
  }

  const hasData = rooms.length > 0;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <h1>CampusSlot</h1>
            <p>Lab and room booking without double bookings</p>
          </div>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!hasData}
          onClick={() => setDialog({ startHour: openHour + 1 })}
        >
          New booking
        </button>
      </header>

      <main>
        <section className="toolbar" aria-label="Choose a day">
          <div className="day-nav">
            <button type="button" className="btn" onClick={() => setDay(shiftDay(day, -1))} aria-label="Previous day">
              Previous
            </button>
            <button type="button" className="btn" onClick={() => setDay(todayString())} disabled={isToday}>
              Today
            </button>
            <button type="button" className="btn" onClick={() => setDay(shiftDay(day, 1))} aria-label="Next day">
              Next
            </button>
          </div>
          <h2 className="day-heading">{formatDayHeading(day)}</h2>
          <label className="day-pick">
            <span className="sr-only">Pick a date</span>
            <input type="date" value={day} onChange={(event) => event.target.value && setDay(event.target.value)} />
          </label>
        </section>

        {error && (
          <div className="banner banner-error" role="alert">
            <span>{error}</span>
            <button type="button" className="btn btn-small" onClick={() => load(true)}>
              Try again
            </button>
          </div>
        )}

        <KpiCards stats={stats} isToday={isToday} />

        {phase === "loading" && <p className="state">Loading the schedule...</p>}

        {phase === "ready" && !hasData && !error && (
          <p className="state">No active rooms yet. Add a room through the API (see /docs) to start booking.</p>
        )}

        {phase === "ready" && hasData && (
          <>
            <Timeline
              rooms={rooms}
              bookings={bookings}
              stats={stats}
              day={day}
              openHour={openHour}
              closeHour={closeHour}
              tzOffset={tzOffset}
              onBookRoom={(room) => setDialog({ roomId: room.id, startHour: openHour + 1 })}
              onSlotClick={(room, hour) => setDialog({ roomId: room.id, startHour: hour })}
              onEditBooking={(booking) => setDialog({ booking })}
            />
            {bookings.length === 0 && <p className="state">No bookings on this day yet. Pick a room and book a slot.</p>}
          </>
        )}
      </main>

      <footer className="footer">
        {info ? (
          <span>
            Build {info.git_sha.slice(0, 7)} / API v{info.version} / {info.environment}
          </span>
        ) : (
          <span>Connecting...</span>
        )}
      </footer>

      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}

      {dialog && (
        <BookingDialog
          key={dialog.booking?.id ?? `new-${dialog.roomId ?? "any"}-${dialog.startHour}`}
          rooms={rooms}
          day={day}
          booking={dialog.booking}
          roomId={dialog.roomId}
          startHour={dialog.startHour}
          onClose={() => setDialog(null)}
          onSaved={handleSaved}
        />
      )}
    </div>
  );
}
