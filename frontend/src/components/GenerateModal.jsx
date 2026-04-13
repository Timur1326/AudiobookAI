import { useEffect, useRef, useState } from "react";
import {
  Modal, Steps, Button, Spin, Tag, Checkbox, Typography,
  Space, Alert, message, Row, Col, Card, Radio,
} from "antd";
import {
  CheckCircleFilled, CloseCircleFilled, LoadingOutlined,
  ClockCircleOutlined, SoundOutlined, PlayCircleOutlined,
} from "@ant-design/icons";
import {
  getBook, runPipeline, getCharacters, listVoices,
  updateCharacterVoice, previewVoice, synthesizeBatch,
} from "../api/client";

const { Text, Title } = Typography;

// ── helpers ───────────────────────────────────────────────────────────────────

const PIPELINE_STEPS = [
  { num: 2, label: "Split quotes"       },
  { num: 3, label: "Detect scenes"      },
  { num: 4, label: "Extract characters" },
  { num: 5, label: "Attribute dialogue" },
  { num: 6, label: "Assign voices"      },
];

function StepStatusIcon({ status }) {
  if (status === "done")    return <CheckCircleFilled  style={{ color: "#22c55e", fontSize: 16 }} />;
  if (status === "running") return <LoadingOutlined    style={{ color: "#6366f1", fontSize: 16 }} />;
  if (status === "error")   return <CloseCircleFilled  style={{ color: "#ef4444", fontSize: 16 }} />;
  return <ClockCircleOutlined style={{ color: "#d1d5db", fontSize: 16 }} />;
}

// ── Step 1: Pipeline progress ────────────────────────────────────────────────

function AnalysisStep({ book, onDone, onError }) {
  const [stepStatuses, setStepStatuses] = useState({});
  const [started,      setStarted]      = useState(false);
  const pollRef = useRef(null);

  const start = async () => {
    setStarted(true);
    try {
      await runPipeline(book, [2, 3, 4, 5, 6], "elevenlabs");
      pollRef.current = setInterval(poll, 2500);
    } catch (e) {
      const status = e.response?.status;
      const detail = e.response?.data?.detail || "Failed to start pipeline";
      if (status === 409) {
        // Stale running state — backend already resets on restart, just retry once
        try {
          await runPipeline(book, [2, 3, 4, 5, 6], "elevenlabs");
          pollRef.current = setInterval(poll, 2500);
        } catch (e2) {
          setStarted(false);
          onError(e2.response?.data?.detail || detail);
        }
      } else {
        setStarted(false);
        onError(detail);
      }
    }
  };

  const poll = async () => {
    try {
      const r = await getBook(book);
      const steps = {};
      for (const s of r.data.steps) steps[s.step] = s.status;
      setStepStatuses(steps);

      const relevant = [2, 3, 4, 5, 6];
      const allDone  = relevant.every(n => steps[n] === "done");
      const anyError = relevant.some(n  => steps[n] === "error");

      if (allDone) {
        clearInterval(pollRef.current);
        onDone();
      } else if (anyError) {
        clearInterval(pollRef.current);
        onError("A pipeline step failed. Check logs.");
      }
    } catch {
      // ignore poll errors
    }
  };

  useEffect(() => () => clearInterval(pollRef.current), []);

  return (
    <div style={{ padding: "8px 0" }}>
      <Text type="secondary" style={{ display: "block", marginBottom: 24 }}>
        The AI will analyse your book: split dialogue, attribute speakers,
        detect scenes and extract characters.
      </Text>

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {PIPELINE_STEPS.map(({ num, label }) => {
          const status = stepStatuses[num] ?? "pending";
          return (
            <div key={num} style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <StepStatusIcon status={status} />
              <Text style={{ flex: 1 }}>{label}</Text>
              {status === "running" && (
                <Tag color="processing">Running...</Tag>
              )}
              {status === "done" && <Tag color="success">Done</Tag>}
              {status === "error" && <Tag color="error">Error</Tag>}
            </div>
          );
        })}
      </div>

      {!started && (
        <Button
          type="primary"
          size="large"
          style={{ marginTop: 32, width: "100%" }}
          onClick={start}
        >
          Start analysis
        </Button>
      )}

      {started && Object.keys(stepStatuses).length === 0 && (
        <div style={{ textAlign: "center", marginTop: 24 }}>
          <Spin /> <Text style={{ marginLeft: 8 }}>Starting...</Text>
        </div>
      )}
    </div>
  );
}

// ── Step 2: Voice casting ─────────────────────────────────────────────────────

function VoiceCastingStep({ book, onDone }) {
  const [characters, setCharacters] = useState([]);
  const [voices,     setVoices]     = useState([]);
  const [loading,    setLoading]    = useState(true);
  const [playing,    setPlaying]    = useState(null);
  const audioRef = useRef(null);

  useEffect(() => {
    Promise.all([getCharacters(book), listVoices(book, "elevenlabs")])
      .then(([cRes, vRes]) => {
        setCharacters(cRes.data.characters);
        setVoices(vRes.data.voices ?? []);
      })
      .finally(() => setLoading(false));
  }, [book]);

  const handleVoiceChange = async (charId, voiceId) => {
    await updateCharacterVoice(book, charId, voiceId, "elevenlabs");
    setCharacters(prev =>
      prev.map(c => c.id === charId ? { ...c, voice_id: voiceId } : c)
    );
  };

  const handlePreview = async (char) => {
    if (!char.voice_id) return message.warning("Assign a voice first");
    const text = char.sample_text || `Hello, I am ${char.name}.`;
    setPlaying(char.id);
    try {
      const r = await previewVoice(book, text, char.voice_id, "elevenlabs");
      const url = URL.createObjectURL(r.data);
      if (audioRef.current) audioRef.current.pause();
      audioRef.current = new Audio(url);
      audioRef.current.play();
      audioRef.current.onended = () => setPlaying(null);
    } catch {
      message.error("Preview failed");
      setPlaying(null);
    }
  };

  if (loading) return <div style={{ textAlign: "center", padding: 40 }}><Spin /></div>;

  return (
    <div>
      <Text type="secondary" style={{ display: "block", marginBottom: 20 }}>
        Review voice assignments. Click ▶ to hear a sample with the character's line.
      </Text>

      <div style={{ display: "flex", flexDirection: "column", gap: 12, maxHeight: 380, overflowY: "auto" }}>
        {characters.map(char => (
          <Card
            key={char.id}
            size="small"
            style={{ borderRadius: 10 }}
            styles={{ body: { padding: "12px 16px" } }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div
                style={{
                  width: 36, height: 36, borderRadius: 8,
                  background: "#ede9fe", display: "flex",
                  alignItems: "center", justifyContent: "center",
                  flexShrink: 0, fontSize: 16,
                }}
              >
                👤
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <Text strong style={{ display: "block" }}>{char.name}</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {[char.gender, char.age, char.personality].filter(Boolean).join(" · ")}
                </Text>
              </div>
              <select
                value={char.voice_id || ""}
                onChange={e => handleVoiceChange(char.id, e.target.value)}
                style={{
                  border: "1px solid #d9d9d9", borderRadius: 8,
                  padding: "4px 8px", fontSize: 13,
                  width: 160, cursor: "pointer",
                }}
              >
                <option value="">— select voice —</option>
                {voices.map(v => (
                  <option key={v.voice_id || v.id} value={v.voice_id || v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
              <Button
                icon={playing === char.id ? <LoadingOutlined /> : <PlayCircleOutlined />}
                size="small"
                onClick={() => handlePreview(char)}
                disabled={!char.voice_id || playing !== null}
              />
            </div>
            {char.sample_text && (
              <Text
                type="secondary"
                italic
                style={{ fontSize: 12, display: "block", marginTop: 8, paddingLeft: 48 }}
              >
                "{char.sample_text.slice(0, 100)}{char.sample_text.length > 100 ? "..." : ""}"
              </Text>
            )}
          </Card>
        ))}
      </div>

      <Button
        type="primary"
        size="large"
        style={{ marginTop: 20, width: "100%" }}
        onClick={onDone}
      >
        Accept voices & continue
      </Button>
    </div>
  );
}

// ── Step 3: Chapter selection ─────────────────────────────────────────────────

const NARRATOR_STYLES = [
  { value: "standard",    label: "Standard",    desc: "No adaptation" },
  { value: "theatrical",  label: "Theatrical",  desc: "Dramatic pauses, expressive voice" },
  { value: "documentary", label: "Documentary", desc: "Calm, authoritative" },
];

function ChapterSelectionStep({ book, chapters, onDone }) {
  const [selected,       setSelected]       = useState([chapters[0]?.id].filter(Boolean));
  const [narratorStyle,  setNarratorStyle]  = useState("standard");

  const toggle = (id) => {
    setSelected(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const selectAll   = () => setSelected(chapters.map(c => c.id));
  const deselectAll = () => setSelected([]);

  return (
    <div>
      <Text type="secondary" style={{ display: "block", marginBottom: 16 }}>
        Select which chapters to synthesize. You can always add more later.
      </Text>

      <Space style={{ marginBottom: 12 }}>
        <Button size="small" onClick={selectAll}>Select all</Button>
        <Button size="small" onClick={deselectAll}>Deselect all</Button>
      </Space>

      <div style={{ maxHeight: 340, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
        {chapters.map((ch, idx) => (
          <div
            key={ch.id}
            onClick={() => toggle(ch.id)}
            style={{
              display: "flex", alignItems: "center", gap: 12,
              padding: "10px 12px", borderRadius: 8, cursor: "pointer",
              background: selected.includes(ch.id) ? "#ede9fe" : "#f9fafb",
              border: selected.includes(ch.id) ? "1px solid #a5b4fc" : "1px solid transparent",
              transition: "all 0.15s",
            }}
          >
            <Checkbox checked={selected.includes(ch.id)} onChange={() => toggle(ch.id)} />
            <div
              style={{
                width: 24, height: 24, borderRadius: 6,
                background: "#e5e7eb", display: "flex",
                alignItems: "center", justifyContent: "center",
                fontSize: 11, fontWeight: 600, color: "#6b7280",
              }}
            >
              {idx + 1}
            </div>
            <Text style={{ flex: 1 }}>{ch.title}</Text>
            {ch.synth_status === "done" && <Tag color="success">Ready</Tag>}
          </div>
        ))}
      </div>

      <div style={{ marginTop: 16, padding: "10px 12px", background: "#f0f2f5", borderRadius: 8 }}>
        <Text type="secondary" style={{ fontSize: 13 }}>
          Selected: <Text strong>{selected.length}</Text> chapter{selected.length !== 1 ? "s" : ""}
        </Text>
      </div>

      {/* Narrator style */}
      <div style={{ marginTop: 20 }}>
        <Text strong style={{ display: "block", marginBottom: 10 }}>Narrator style</Text>
        <Radio.Group
          value={narratorStyle}
          onChange={e => setNarratorStyle(e.target.value)}
          style={{ display: "flex", flexDirection: "column", gap: 8 }}
        >
          {NARRATOR_STYLES.map(s => (
            <Radio key={s.value} value={s.value}>
              <Text strong>{s.label}</Text>
              <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>{s.desc}</Text>
            </Radio>
          ))}
        </Radio.Group>
      </div>

      <Button
        type="primary"
        size="large"
        disabled={selected.length === 0}
        style={{ marginTop: 20, width: "100%" }}
        onClick={() => onDone(selected, narratorStyle)}
      >
        Synthesize {selected.length} chapter{selected.length !== 1 ? "s" : ""}
      </Button>
    </div>
  );
}

// ── Step 4: Synthesis progress ────────────────────────────────────────────────

function SynthesisStep({ book, chapterIds, chapters, narratorStyle, onClose }) {
  const [statuses, setStatuses] = useState({});
  const pollRef    = useRef(null);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    synthesizeBatch(book, chapterIds, "elevenlabs", narratorStyle).catch(() =>
      message.error("Failed to start synthesis")
    );
    pollRef.current = setInterval(poll, 2500);
    return () => clearInterval(pollRef.current);
  }, []);

  const poll = async () => {
    try {
      const r = await getBook(book);
      const m = {};
      for (const ch of r.data.chapters) m[ch.id] = ch.synth_status;
      setStatuses(m);

      const allDone = chapterIds.every(id => m[id] === "done" || m[id] === "error");
      if (allDone) clearInterval(pollRef.current);
    } catch {
      // ignore
    }
  };

  const selectedChapters = chapters.filter(c => chapterIds.includes(c.id));
  const doneCount = chapterIds.filter(id => statuses[id] === "done").length;

  return (
    <div>
      <Text type="secondary" style={{ display: "block", marginBottom: 16 }}>
        Synthesizing audio for selected chapters...
      </Text>

      <div style={{ marginBottom: 16 }}>
        <Text strong>{doneCount}</Text>
        <Text type="secondary"> / {chapterIds.length} chapters done</Text>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 340, overflowY: "auto" }}>
        {selectedChapters.map((ch, idx) => {
          const status = statuses[ch.id] ?? "pending";
          return (
            <div
              key={ch.id}
              style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "10px 14px", borderRadius: 8, background: "#f9fafb",
              }}
            >
              <StepStatusIcon status={status} />
              <div style={{ flex: 1 }}>
                <Text style={{ fontSize: 13 }}>{ch.title}</Text>
              </div>
              {status === "running" && <Tag color="processing">Synthesizing...</Tag>}
              {status === "done"    && <Tag color="success">Done</Tag>}
              {status === "error"   && <Tag color="error">Error</Tag>}
              {status === "pending" && <Tag>Waiting</Tag>}
            </div>
          );
        })}
      </div>

      {doneCount === chapterIds.length && (
        <Alert
          type="success"
          message="All chapters synthesized!"
          style={{ marginTop: 16 }}
        />
      )}

      <Button
        style={{ marginTop: 16, width: "100%" }}
        onClick={onClose}
      >
        Close & go to book
      </Button>
    </div>
  );
}

// ── Main modal ────────────────────────────────────────────────────────────────

const MODAL_STEPS = ["Analysis", "Voice casting", "Select chapters", "Synthesis"];

export default function GenerateModal({ open, book, chapters, onClose }) {
  const [current,       setCurrent]       = useState(0);
  const [error,         setError]         = useState(null);
  const [synthIds,      setSynthIds]      = useState([]);
  const [narratorStyle, setNarratorStyle] = useState("standard");

  // On open: check pipeline status and jump to correct step
  useEffect(() => {
    if (!open) return;
    getBook(book).then(r => {
      const steps = {};
      for (const s of r.data.steps) steps[s.step] = s.status;
      const analysisDone = [2, 3, 4, 5, 6].every(n => steps[n] === "done");
      if (analysisDone) setCurrent(1);  // jump to voice casting
      else setCurrent(0);
    }).catch(() => {});
  }, [open]);

  const reset = () => {
    setCurrent(0);
    setError(null);
    setSynthIds([]);
    setNarratorStyle("standard");
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  return (
    <Modal
      open={open}
      onCancel={handleClose}
      footer={null}
      width={560}
      title={
        <Space>
          <SoundOutlined style={{ color: "#6366f1" }} />
          <span>Generate Audiobook</span>
        </Space>
      }
      destroyOnClose
    >
      {/* Stepper */}
      <Steps
        current={current}
        size="small"
        style={{ marginBottom: 28 }}
        items={MODAL_STEPS.map(label => ({ title: label }))}
      />

      {/* Error */}
      {error && (
        <Alert
          type="error"
          message={error}
          closable
          onClose={() => setError(null)}
          style={{ marginBottom: 16 }}
        />
      )}

      {/* Step content */}
      {current === 0 && (
        <AnalysisStep
          book={book}
          onDone={() => { setError(null); setCurrent(1); }}
          onError={setError}
        />
      )}

      {current === 1 && (
        <VoiceCastingStep
          book={book}
          onDone={() => setCurrent(2)}
        />
      )}

      {current === 2 && (
        <ChapterSelectionStep
          book={book}
          chapters={chapters}
          onDone={(ids, style) => { setSynthIds(ids); setNarratorStyle(style); setCurrent(3); }}
        />
      )}

      {current === 3 && (
        <SynthesisStep
          book={book}
          chapterIds={synthIds}
          chapters={chapters}
          narratorStyle={narratorStyle}
          onClose={handleClose}
        />
      )}
    </Modal>
  );
}