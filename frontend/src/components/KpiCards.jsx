export default function KpiCards({ stats, isToday }) {
  const busiest = stats?.busiest_room;
  const cards = [
    {
      label: isToday ? "Bookings today" : "Bookings this day",
      value: stats ? stats.day_confirmed : "-",
      hint: stats ? `${stats.total_confirmed} confirmed in total` : "",
    },
    {
      label: "Average utilisation",
      value: stats ? `${stats.average_utilisation_pct}%` : "-",
      hint: "of opening hours, across active rooms",
    },
    {
      label: "Rooms in use now",
      value: stats ? stats.rooms_in_use_now : "-",
      hint: stats ? `of ${stats.rooms.length} active rooms` : "",
    },
    {
      label: "Busiest room",
      value: busiest ? busiest.name : "None yet",
      hint: busiest ? `${Math.round(busiest.booked_minutes / 60 * 10) / 10} h booked` : "No bookings on this day",
    },
  ];

  return (
    <section className="kpis" aria-label="Key figures">
      {cards.map((card) => (
        <article className="kpi" key={card.label}>
          <p className="kpi-label">{card.label}</p>
          <p className="kpi-value">{card.value}</p>
          <p className="kpi-hint">{card.hint}</p>
        </article>
      ))}
    </section>
  );
}
