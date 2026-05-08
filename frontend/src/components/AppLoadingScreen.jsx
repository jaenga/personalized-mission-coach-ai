import loadingImg from "../assets/tomato/_shared/loading.svg";
import { BottomNav } from "./Home.jsx";

export default function AppLoadingScreen({
  active = "home",
  message = "불러오는 중 ...",
  onNavigate,
}) {
  return (
    <div className="mobile-frame flex flex-col" style={{ background: "#fdefea" }}>
      <div
        className="flex-1 flex flex-col items-center justify-center"
        style={{ paddingBottom: "calc(88px + env(safe-area-inset-bottom))" }}
      >
        <img
          src={loadingImg}
          alt=""
          draggable="false"
          className="select-none pointer-events-none tomato-float"
          style={{ width: 112, height: 112, objectFit: "contain" }}
        />
        <div
          className="font-sejong"
          style={{
            marginTop: 14,
            color: "#E35D49",
            fontSize: 15,
            fontWeight: 700,
            letterSpacing: "-0.43px",
          }}
        >
          {message}
        </div>
      </div>
      <BottomNav active={active} onChange={onNavigate} />
    </div>
  );
}
