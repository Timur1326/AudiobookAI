import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Typography, Spin, Button, Tag, Steps, Card,
  List, message, Tooltip,
} from "antd";
import {
  ArrowLeftOutlined, CheckCircleFilled, ClockCircleOutlined,
  LoadingOutlined, CloseCircleFilled,
  TeamOutlined, ThunderboltOutlined,
  DownloadOutlined,
} from "@ant-design/icons";
import { getBook, getAudioUrl } from "../api/client";
import GenerateModal from "../components/GenerateModal";

const { Title, Text } = Typography;

const STEP_LABELS = [
  "Parse",
  "Quotes",
  "Scenes",
  "Characters",
  "Attribution",
  "Voices",
  "Synthesis",
];

const SYNTH_STATUS_TAG = {
  done:    <Tag color="success">Ready</Tag>,
  running: <Tag color="processing">Synthesizing...</Tag>,
  error:   <Tag color="error">Error</Tag>,
  pending: <Tag color="default">Pending</Tag>,
};

function StepIcon({ status }) {
  if (status === "done")    return <CheckCircleFilled  style={{ color: "#22c55e" }} />;
  if (status === "running") return <LoadingOutlined    style={{ color: "#f97316" }} />;
  if (status === "error")   return <CloseCircleFilled  style={{ color: "#ef4444" }} />;
  return <ClockCircleOutlined style={{ color: "#d1d5db" }} />;
}

function PipelineCard({ steps }) {
  const items = STEP_LABELS.map((label, i) => {
    const stepNum = i + 1;
    const s       = steps.find(s => s.step === stepNum);
    const status  = s?.status ?? "pending";
    return {
      title: label,
      status: status === "done"    ? "finish"
            : status === "running" ? "process"
            : status === "error"   ? "error"
            : "wait",
      icon: <StepIcon status={status} />,
    };
  });

  return (
    <Card
      style={{ borderRadius: 12, marginBottom: 24 }}
      styles={{ body: { padding: "20px 24px" } }}
    >
      <Text strong style={{ fontSize: 13, color: "#6b7280", display: "block", marginBottom: 16 }}>
        PIPELINE
      </Text>
      <Steps items={items} size="small" />
    </Card>
  );
}

function StatCard({ icon, label, value }) {
  return (
    <Card style={{ borderRadius: 12 }} styles={{ body: { padding: "16px 20px" } }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div
          style={{
            width: 40, height: 40, borderRadius: 10,
            background: "#e8f4f7", display: "flex",
            alignItems: "center", justifyContent: "center",
            flexShrink: 0,
          }}
        >
          {icon}
        </div>
        <div>
          <Text style={{ fontSize: 20, fontWeight: 700, display: "block", lineHeight: 1.2 }}>
            {value}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{label}</Text>
        </div>
      </div>
    </Card>
  );
}

export default function BookPage() {
  const { book }              = useParams();
  const [data,     setData]     = useState(null);
  const [loading,  setLoading]  = useState(true);
  const [modal,    setModal]    = useState(false);
  const pollRef = useRef(null);
  const navigate = useNavigate();

  const load = () =>
    getBook(book)
      .then(r => setData(r.data))
      .catch(() => message.error("Failed to load book"))
      .finally(() => setLoading(false));

  useEffect(() => {
    if (!data) return;
    const isRunning = data.steps?.some(s => s.status === "running");
    if (isRunning && !pollRef.current) {
      pollRef.current = setInterval(() => {
        getBook(book).then(r => {
          setData(r.data);
          const stillRunning = r.data.steps?.some(s => s.status === "running");
          if (!stillRunning) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        });
      }, 2500);
    }
  }, [data]);

  useEffect(() => { load(); }, [book]);



  if (loading) return (
    <div style={{ textAlign: "center", paddingTop: 100 }}>
      <Spin size="large" />
    </div>
  );

  if (!data) return (
    <div style={{ textAlign: "center", paddingTop: 100 }}>
      <Text type="secondary">Book not found</Text>
    </div>
  );

  const createdDate = data.created_at
    ? new Date(data.created_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })
    : "";

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "36px 24px" }}>

      {/* Back */}
      <Button
        icon={<ArrowLeftOutlined />}
        style={{ marginBottom: 24 }}
        onClick={() => navigate("/")}
      >
        Library
      </Button>

      {/* Book header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 28 }}>
        <div>
          <Title level={2} style={{ margin: 0 }}>{data.title}</Title>
          <Text type="secondary" style={{ fontSize: 15 }}>
            {data.author}
            {createdDate && <> · Uploaded {createdDate}</>}
          </Text>
        </div>
        <div style={{ display: "flex", gap: 10, flexShrink: 0 }}>
          <Button
            size="large"
            icon={<TeamOutlined />}
            onClick={() => navigate(`/books/${book}/characters`)}
          >
            Characters
          </Button>
          <Button
            type="primary"
            size="large"
            icon={<ThunderboltOutlined />}
            onClick={() => setModal(true)}
          >
            Generate Audiobook
          </Button>
        </div>
      </div>

      {/* Pipeline stepper */}
      {data.steps?.length > 0 && <PipelineCard steps={data.steps} />}

      {/* Generate modal */}
      <GenerateModal
        open={modal}
        book={book}
        chapters={data.chapters ?? []}
        onClose={() => { setModal(false); load(); }}
      />

      {/* Chapters list */}
      <Card
        style={{ borderRadius: 12 }}
        styles={{ body: { padding: 0 } }}
        title={
          <Text strong style={{ fontSize: 14, color: "#6b7280" }}>
            CHAPTERS
          </Text>
        }
      >
        <List
          dataSource={data.chapters}
          renderItem={(ch, idx) => (
            <List.Item
              style={{
                padding: "14px 24px",
                cursor: "pointer",
                transition: "background 0.15s",
              }}
              onMouseEnter={e => e.currentTarget.style.background = "#f9fafb"}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
              onClick={() => navigate(`/books/${book}/chapters/${ch.id}`)}
              extra={
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  {SYNTH_STATUS_TAG[ch.synth_status] ?? SYNTH_STATUS_TAG.pending}
                  {ch.synth_status === "done" && (
                    <Tooltip title="Download">
                      <Button
                        size="small"
                        icon={<DownloadOutlined />}
                        onClick={e => {
                          e.stopPropagation();
                          const a = document.createElement("a");
                          a.href = getAudioUrl(book, ch.id, ch.synth_engine || "elevenlabs");
                          a.download = `${ch.title}.mp3`;
                          a.click();
                        }}
                      />
                    </Tooltip>
                  )}
                </div>
              }
            >
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div
                  style={{
                    width: 28, height: 28, borderRadius: 8,
                    background: "#f3f4f6", display: "flex",
                    alignItems: "center", justifyContent: "center",
                    fontSize: 12, fontWeight: 600, color: "#6b7280",
                    flexShrink: 0,
                  }}
                >
                  {idx + 1}
                </div>
                <Text style={{ fontSize: 14 }}>{ch.title}</Text>
              </div>
            </List.Item>
          )}
        />
      </Card>

    </div>
  );
}