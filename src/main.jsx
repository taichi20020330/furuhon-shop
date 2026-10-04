import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import App from "./App.jsx";
import "./styles/space.css";
import "./styles/app.css";

createRoot(document.getElementById("root")).render(<HashRouter><App /></HashRouter>);
