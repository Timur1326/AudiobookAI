import { BrowserRouter, Routes, Route, useNavigate, Navigate } from "react-router-dom";
import { ConfigProvider, Layout, Typography, Space, Button } from "antd";
import { AudioOutlined, LogoutOutlined } from "@ant-design/icons";
import BooksPage     from "./pages/BooksPage";
import BookPage      from "./pages/BookPage";
import ChapterPage   from "./pages/ChapterPage";
import CharactersPage from "./pages/CharactersPage";
import AuthPage      from "./pages/AuthPage";
import { isLoggedIn, clearAuth, getUser } from "./auth";

const { Header, Content } = Layout;

function AppHeader() {
  const navigate = useNavigate();
  const user     = getUser();

  function logout() {
    clearAuth();
    navigate("/auth");
  }

  return (
    <Header style={{
      background: "#fff",
      borderBottom: "1px solid #e8e8e8",
      padding: "0 32px",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      height: 56,
    }}>
      <Space style={{ cursor: "pointer", userSelect: "none" }} onClick={() => navigate("/")}>
        <AudioOutlined style={{ fontSize: 20, color: "#5a9dad" }} />
        <Typography.Text style={{ fontSize: 16, fontWeight: 700, color: "#1a1a2e" }}>
          AudiobookAI
        </Typography.Text>
      </Space>

      {user && (
        <Space>
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>{user.email}</Typography.Text>
          <Button size="small" icon={<LogoutOutlined />} onClick={logout}>Logout</Button>
        </Space>
      )}
    </Header>
  );
}

function ProtectedLayout({ children }) {
  if (!isLoggedIn()) return <Navigate to="/auth" replace />;
  return (
    <Layout style={{ minHeight: "100vh", background: "#f0f2f5" }}>
      <AppHeader />
      <Content>{children}</Content>
    </Layout>
  );
}

export default function App() {
  return (
    <ConfigProvider theme={{
      token: {
        colorPrimary: "#5a9dad",
        borderRadius: 10,
        fontFamily: "Inter, system-ui, sans-serif",
      },
    }}>
      <BrowserRouter>
        <Routes>
          {/* Auth */}
          <Route path="/auth" element={<AuthPage />} />

          {/* Chapter reader — full-screen, no header */}
          <Route path="/books/:book/chapters/:chapterId" element={<ChapterPage />} />

          {/* Protected pages */}
          <Route path="/" element={
            <ProtectedLayout><BooksPage /></ProtectedLayout>
          } />
          <Route path="/books/:book" element={
            <ProtectedLayout><BookPage /></ProtectedLayout>
          } />
          <Route path="/books/:book/characters" element={
            <ProtectedLayout><CharactersPage /></ProtectedLayout>
          } />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}