// Pure date helpers. Every function that depends on a timezone takes the offset explicitly
// (minutes the viewer is ahead of UTC) so the behaviour is deterministic and easy to test.

const pad = (n) => String(n).padStart(2, "0");

export function toDateString(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function todayString() {
  return toDateString(new Date());
}

export function shiftDay(dateString, days) {
  const [y, m, d] = dateString.split("-").map(Number);
  return toDateString(new Date(y, m - 1, d + days));
}

// Offset in effect around midday of the given local day (stays correct across DST changes).
export function offsetForDay(dateString) {
  const [y, m, d] = dateString.split("-").map(Number);
  return -new Date(y, m - 1, d, 12).getTimezoneOffset();
}

// A local "YYYY-MM-DD" + "HH:MM" as epoch milliseconds, for a viewer at the given offset.
function localToEpoch(dateString, timeString, offsetMinutes) {
  const [y, m, d] = dateString.split("-").map(Number);
  const [hh, mm] = timeString.split(":").map(Number);
  return Date.UTC(y, m - 1, d, hh, mm) - offsetMinutes * 60000;
}

export function localToIso(dateString, timeString, offsetMinutes) {
  return new Date(localToEpoch(dateString, timeString, offsetMinutes)).toISOString();
}

export function isoToLocalParts(iso, offsetMinutes) {
  const shifted = new Date(new Date(iso).getTime() + offsetMinutes * 60000);
  const hours = shifted.getUTCHours();
  const minutes = shifted.getUTCMinutes();
  return {
    date: `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`,
    time: `${pad(hours)}:${pad(minutes)}`,
  };
}

export function formatRange(startIso, endIso, offsetMinutes) {
  const start = isoToLocalParts(startIso, offsetMinutes).time;
  const end = isoToLocalParts(endIso, offsetMinutes).time;
  return `${start} to ${end}`;
}

// Where a booking sits on a timeline that spans [openHour, closeHour) of the given local day.
// Returns null when it lies completely outside the window.
export function blockPosition(booking, dateString, openHour, closeHour, offsetMinutes) {
  const midnight = localToEpoch(dateString, "00:00", offsetMinutes);
  const startMin = (new Date(booking.start_time).getTime() - midnight) / 60000;
  const endMin = (new Date(booking.end_time).getTime() - midnight) / 60000;
  const windowStart = openHour * 60;
  const windowEnd = closeHour * 60;
  if (endMin <= windowStart || startMin >= windowEnd) return null;

  const visibleStart = Math.max(startMin, windowStart);
  const visibleEnd = Math.min(endMin, windowEnd);
  const span = windowEnd - windowStart;
  return {
    leftPct: ((visibleStart - windowStart) / span) * 100,
    widthPct: ((visibleEnd - visibleStart) / span) * 100,
    clippedStart: startMin < windowStart,
    clippedEnd: endMin > windowEnd,
  };
}

export function hourLabels(openHour, closeHour) {
  const labels = [];
  for (let hour = openHour; hour < closeHour; hour += 1) labels.push(`${pad(hour)}:00`);
  return labels;
}

export function formatDayHeading(dateString) {
  const [y, m, d] = dateString.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}
