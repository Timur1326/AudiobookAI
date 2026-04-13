import { useState } from "react";
import { Card, Form, Input, Button, Typography, Tabs, message } from "antd";
import { AudioOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { authLogin, authRegister } from "../api/client";
import { saveAuth } from "../auth";

const { Title, Text } = Typography;

export default function AuthPage() {
  const navigate       = useNavigate();
  const [loading, setLoading] = useState(false);
  const [tab, setTab]  = useState("login");

  async function handleSubmit({ email, password }) {
    setLoading(true);
    try {
      const fn  = tab === "login" ? authLogin : authRegister;
      const res = await fn(email, password);
      saveAuth(res.data.token, { id: res.data.id, email: res.data.email });
      message.success(tab === "login" ? "Logged in" : "Account created");
      navigate("/");
    } catch (err) {
      const detail = err.response?.data?.detail;
      message.error(detail || "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      minHeight: "100vh",
      background: "#f0f2f5",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    }}>
      <Card style={{ width: 380, borderRadius: 12 }}>
        <div style={{ textAlign: "center", marginBottom: 24 }}>
          <AudioOutlined style={{ fontSize: 28, color: "#6366f1" }} />
          <Title level={4} style={{ margin: "8px 0 0" }}>Audiobook Studio</Title>
        </div>

        <Tabs
          activeKey={tab}
          onChange={setTab}
          centered
          items={[
            { key: "login",    label: "Login" },
            { key: "register", label: "Register" },
          ]}
        />

        <Form layout="vertical" onFinish={handleSubmit} style={{ marginTop: 8 }}>
          <Form.Item
            name="email"
            rules={[
              { required: true, message: "Enter email" },
              { type: "email", message: "Invalid email" },
            ]}
          >
            <Input placeholder="Email" size="large" />
          </Form.Item>

          <Form.Item
            name="password"
            rules={[
              { required: true, message: "Enter password" },
              { min: 6, message: "Min 6 characters" },
            ]}
          >
            <Input.Password placeholder="Password" size="large" />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0 }}>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              block
              size="large"
            >
              {tab === "login" ? "Login" : "Create account"}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}