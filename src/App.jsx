import { Routes, Route, Navigate } from "react-router-dom";
import ShelfPage from "./pages/ShelfPage.jsx";
import ShelfListPage from "./pages/ShelfListPage.jsx";
import SignupPage from "./pages/SignupPage.jsx";
import UploadPage from "./pages/UploadPage.jsx";
import ManagePage from "./pages/ManagePage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import { OWNER_ID } from "./data/repo.js";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ShelfPage id={OWNER_ID} home />} />
      <Route path="/shelves" element={<ShelfListPage />} />
      <Route path="/s/:id" element={<ShelfPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/upload" element={<UploadPage />} />
      <Route path="/manage" element={<ManagePage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
