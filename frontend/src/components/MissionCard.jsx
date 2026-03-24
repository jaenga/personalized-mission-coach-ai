export default function MissionCard({ mission }) {
  return (
    <div className="card" style={{ borderLeft: "4px solid #5b9cf6" }}>
      <h2>오늘의 미션 🎯</h2>
      <p style={{ fontSize: "1.15rem", fontWeight: 700, margin: "8px 0 4px" }}>
        {mission.title}
      </p>
      <p style={{ color: "#555", fontSize: "0.9rem" }}>{mission.description}</p>
    </div>
  );
}
