import { useEffect, useRef, useState } from "react";
import {
  Modal, Steps, Button, Spin, Tag, Checkbox, Typography,
  Space, Alert, message, Card, Radio, Input, Select,
} from "antd";
import {
  CheckCircleFilled, CloseCircleFilled, LoadingOutlined,
  ClockCircleOutlined, SoundOutlined, PlayCircleOutlined,
  PauseCircleOutlined, BulbOutlined,
} from "@ant-design/icons";
import {
  getBook, runPipeline, getCharacters, listVoices,
  updateCharacterVoice, previewVoice, synthesizeBatch,
  searchAmbient, generateAmbient, getAmbientConfig, assignSceneAmbient,
  BASE_URL,
} from "../api/client";

const { Text } = Typography;

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
  if (status === "running") return <LoadingOutlined    style={{ color: "#5a9dad", fontSize: 16 }} />;
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
        The AI will analyse your book.
      </Text>

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {PIPELINE_STEPS.map(({ num, label }) => {
          const status = stepStatuses[num] ?? "pending";
          return (
            <div key={num} style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <StepStatusIcon status={status} />
              <Text style={{ flex: 1 }}>{label}</Text>
              {status === "running" && <Tag color="processing">Running...</Tag>}
              {status === "done"    && <Tag color="success">Done</Tag>}
              {status === "error"   && <Tag color="error">Error</Tag>}
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
        Review voice assignments.
      </Text>

      <div style={{ display: "flex", flexDirection: "column", gap: 12, maxHeight: 380, overflowY: "auto" }}>
        {characters.map(char => (
          <Card
            key={char.id}
            size="small"
            style={{ borderRadius: 10 }}
            styles={{ body: { padding: "12px 16px" } }}
          >
            <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
              <div style={{
                width: 36, height: 36, borderRadius: 8,
                background: "#e8f4f7", display: "flex",
                alignItems: "center", justifyContent: "center",
                flexShrink: 0, fontSize: 16,
              }}>
                👤
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <Text strong style={{ display: "block" }}>{char.name}</Text>
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 6 }}>
                  {[char.gender, char.age, char.personality].filter(Boolean).join(" · ")}
                </Text>
                <div style={{ display: "flex", gap: 8 }}>
                  <Select
                    value={char.voice_id || undefined}
                    placeholder="— select voice —"
                    onChange={voiceId => handleVoiceChange(char.id, voiceId)}
                    style={{ flex: 1 }}
                    size="small"
                    showSearch
                    optionFilterProp="label"
                    options={voices.map(v => ({ value: v.voice_id || v.id, label: v.name }))}
                    getPopupContainer={trigger => trigger.parentElement}
                  />
                  <Button
                    icon={playing === char.id ? <LoadingOutlined /> : <PlayCircleOutlined />}
                    size="small"
                    onClick={() => handlePreview(char)}
                    disabled={!char.voice_id || playing !== null}
                  />
                </div>
              </div>
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
  { value: "theatrical",  label: "Theatrical",  desc: "Dramatic pauses, expressive voice" },
  { value: "documentary", label: "Documentary", desc: "Calm, authoritative" },
];

const TTS_ENGINES = [
  { value: "elevenlabs", label: "ElevenLabs", desc: "Cloud, high quality" },
  { value: "xtts",       label: "XTTS v2",    desc: "Local, medium quality" },
];

function ChapterSelectionStep({ book, chapters, onDone }) {
  const [selected,      setSelected]      = useState([chapters[0]?.id].filter(Boolean));
  const [narratorStyle, setNarratorStyle] = useState("theatrical");
  const [engine,        setEngine]        = useState("elevenlabs");

  const toggle = (id) =>
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);

  const selectAll   = () => setSelected(chapters.map(c => c.id));
  const deselectAll = () => setSelected([]);

  return (
    <div>
      <Text type="secondary" style={{ display: "block", marginBottom: 16 }}>
        Select chapters to synthesize.
      </Text>

      <Space style={{ marginBottom: 12 }}>
        <Button size="small" onClick={selectAll}>Select all</Button>
        <Button size="small" onClick={deselectAll}>Deselect all</Button>
      </Space>

      <div style={{ maxHeight: 260, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
        {chapters.map((ch, idx) => {
          const isSynth = ch.synth_status === "done";
          return (
            <div
              key={ch.id}
              onClick={() => toggle(ch.id)}
              style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "10px 12px", borderRadius: 8,
                cursor: "pointer",
                background: selected.includes(ch.id) ? "#e8f4f7" : "#f9fafb",
                border: selected.includes(ch.id) ? "1px solid #a5b4fc" : "1px solid transparent",
                transition: "all 0.15s",
              }}
            >
              <Checkbox checked={selected.includes(ch.id)} onChange={() => toggle(ch.id)} />
              <div style={{
                width: 24, height: 24, borderRadius: 6,
                background: "#e5e7eb", display: "flex",
                alignItems: "center", justifyContent: "center",
                fontSize: 11, fontWeight: 600, color: "#6b7280", flexShrink: 0,
              }}>
                {idx + 1}
              </div>
              <Text style={{ flex: 1, fontSize: 13 }}>{ch.title}</Text>
              {isSynth && <Tag color="success">Ready</Tag>}
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: 12, padding: "10px 12px", background: "#f0f2f5", borderRadius: 8 }}>
        <Text type="secondary" style={{ fontSize: 13 }}>
          Selected: <Text strong>{selected.length}</Text> chapter{selected.length !== 1 ? "s" : ""}
        </Text>
      </div>

      {/* TTS Engine */}
      <div style={{ marginTop: 16 }}>
        <Text strong style={{ display: "block", marginBottom: 10 }}>TTS Engine</Text>
        <Radio.Group
          value={engine}
          onChange={e => setEngine(e.target.value)}
          style={{ display: "flex", flexDirection: "column", gap: 8 }}
        >
          {TTS_ENGINES.map(e => (
            <Radio key={e.value} value={e.value}>
              <Text strong>{e.label}</Text>
              <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>{e.desc}</Text>
            </Radio>
          ))}
        </Radio.Group>
      </div>

      {/* Narrator style */}
      <div style={{ marginTop: 16 }}>
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
        style={{ marginTop: 16, width: "100%" }}
        onClick={() => onDone(selected, narratorStyle, engine)}
      >
        Continue →
      </Button>
    </div>
  );
}

// ── Step 4: Ambient sound ─────────────────────────────────────────────────────

function AmbientStep({ book, chapters, chapterIds, engine, onDone }) {
  const selectedChapters = chapters.filter(c => chapterIds.includes(c.id));

  const [openChId,      setOpenChId]      = useState(null);
  const [chapterScenes, setChapterScenes] = useState({});   // chId → scenes[]
  const [suggesting,    setSuggesting]    = useState({});   // chId → bool
  const [changingScene, setChangingScene] = useState(null); // scene_id | null
  const [searchQuery,   setSearchQuery]   = useState({});   // sceneId → string
  const [searchResults, setSearchResults] = useState({});   // sceneId → results[]
  const [searching,     setSearching]     = useState({});   // sceneId → bool
  const [playingUrl,    setPlayingUrl]    = useState(null);
  const audioRef  = useRef(null);
  const pollRefs  = useRef({});

  useEffect(() => () => {
    if (audioRef.current) audioRef.current.pause();
    Object.values(pollRefs.current).forEach(clearInterval);
  }, []);

  const stopAudio = () => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null; }
    setPlayingUrl(null);
  };

  const playPreview = (url) => {
    if (playingUrl === url) { stopAudio(); return; }
    stopAudio();
    const a = new Audio(url);
    a.play().catch(() => {});
    a.onended = () => setPlayingUrl(null);
    audioRef.current = a;
    setPlayingUrl(url);
  };

  const loadScenes = async (chId) => {
    try {
      const r = await getAmbientConfig(book, chId, engine);
      setChapterScenes(prev => ({ ...prev, [chId]: r.data.scenes || [] }));
    } catch {}
  };

  const toggleChapter = async (chId) => {
    if (openChId === chId) { setOpenChId(null); return; }
    setOpenChId(chId);
    if (!chapterScenes[chId]) await loadScenes(chId);
  };

  const doSuggest = async (chId, e) => {
    e.stopPropagation();
    if (openChId !== chId) setOpenChId(chId);
    setSuggesting(prev => ({ ...prev, [chId]: true }));
    try {
      await generateAmbient(book, chId, engine);
      pollRefs.current[chId] = setInterval(async () => {
        const r = await getAmbientConfig(book, chId, engine);
        if (r.data.status === "done") {
          clearInterval(pollRefs.current[chId]);
          setSuggesting(prev => ({ ...prev, [chId]: false }));
          setChapterScenes(prev => ({ ...prev, [chId]: r.data.scenes || [] }));
        } else if (r.data.status === "error") {
          clearInterval(pollRefs.current[chId]);
          setSuggesting(prev => ({ ...prev, [chId]: false }));
          message.error("AI suggestion failed");
        }
      }, 2000);
    } catch {
      setSuggesting(prev => ({ ...prev, [chId]: false }));
      message.error("Failed to start AI suggest");
    }
  };

  const doSearch = async (sceneId) => {
    const q = searchQuery[sceneId];
    if (!q?.trim()) return;
    setSearching(prev => ({ ...prev, [sceneId]: true }));
    try {
      const r = await searchAmbient(book, q);
      setSearchResults(prev => ({ ...prev, [sceneId]: r.data.results || [] }));
    } catch { message.error("Search failed"); }
    finally { setSearching(prev => ({ ...prev, [sceneId]: false })); }
  };

  const doAssignScene = async (chId, sceneId, result, resultIdx) => {
    try {
      await assignSceneAmbient(book, sceneId, result.id, result.preview_url, engine);
      setChapterScenes(prev => ({
        ...prev,
        [chId]: (prev[chId] || []).map(s =>
          s.scene_id === sceneId
            ? { ...s, sound_url: `/ambient-files/${result.id}.mp3` }
            : s
        ),
      }));
      setChangingScene(null);
      setSearchResults(prev => ({ ...prev, [sceneId]: [] }));
      stopAudio();
      message.success(`Sound ${resultIdx + 1} assigned to scene`);
    } catch { message.error("Failed to assign sound"); }
  };

  const hasAmbient = (chId) =>
    (chapterScenes[chId] || []).some(s => s.sound_url);

  return (
    <div>
      <Text type="secondary" style={{ display: "block", marginBottom: 16 }}>
        Set ambient sound per scene. Optional — click Continue to skip.
      </Text>

      <div style={{ maxHeight: 400, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
        {selectedChapters.map((ch, idx) => {
          const scenes    = chapterScenes[ch.id] || [];
          const isOpen    = openChId === ch.id;
          const isSuggest = suggesting[ch.id];

          return (
            <div key={ch.id}>
              {/* Chapter header */}
              <div
                onClick={() => toggleChapter(ch.id)}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "10px 12px",
                  borderRadius: isOpen ? "8px 8px 0 0" : 8,
                  cursor: "pointer",
                  background: "#f9fafb",
                  border: "1px solid #e5e7eb",
                  transition: "all 0.15s",
                }}
              >
                <div style={{
                  width: 24, height: 24, borderRadius: 6,
                  background: "#e5e7eb", display: "flex",
                  alignItems: "center", justifyContent: "center",
                  fontSize: 11, fontWeight: 600, color: "#6b7280", flexShrink: 0,
                }}>
                  {idx + 1}
                </div>
                <Text style={{ flex: 1, fontSize: 13 }}>{ch.title}</Text>
                {hasAmbient(ch.id) && <Tag color="success" style={{ margin: 0 }}>Ambient set</Tag>}
                <Button
                  size="small"
                  icon={<BulbOutlined />}
                  loading={isSuggest}
                  onClick={e => doSuggest(ch.id, e)}
                >
                  AI suggest
                </Button>
              </div>

              {/* Scenes panel */}
              {isOpen && (
                <div style={{
                  padding: "10px 12px",
                  background: "#f0f9ff",
                  border: "1px solid #bae6fd",
                  borderTop: "none",
                  borderRadius: "0 0 8px 8px",
                }}>
                  {isSuggest && (
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                      <Spin size="small" />
                      <Text type="secondary" style={{ fontSize: 12 }}>AI is selecting sounds...</Text>
                    </div>
                  )}

                  {!isSuggest && scenes.length === 0 && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      No scenes found. Run AI suggest or make sure scene detection completed.
                    </Text>
                  )}

                  {scenes.map((scene, si) => {
                    const soundUrl   = scene.sound_url ? `${BASE_URL}${scene.sound_url}` : null;
                    const isChanging = changingScene === scene.scene_id;
                    const results    = searchResults[scene.scene_id] || [];

                    return (
                      <div key={scene.scene_id} style={{
                        marginBottom: si < scenes.length - 1 ? 6 : 0,
                        padding: "8px 10px",
                        background: "#fff",
                        borderRadius: 6,
                        border: "1px solid #e5e7eb",
                      }}>
                        {/* Scene row */}
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <Text style={{ fontSize: 12, color: "#6b7280", flexShrink: 0 }}>
                            Scene {si + 1}
                          </Text>
                          <Text type="secondary" style={{ fontSize: 12, flex: 1, overflow: "hidden",
                            textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {scene.location || "—"}
                          </Text>
                          {soundUrl && (
                            <Button
                              size="small" shape="circle"
                              icon={playingUrl === soundUrl ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                              onClick={() => playPreview(soundUrl)}
                            />
                          )}
                          {soundUrl && !scene.location && (
                            <Tag color="success" style={{ margin: 0, fontSize: 11 }}>✓</Tag>
                          )}
                          <Button
                            size="small"
                            type={isChanging ? "default" : "text"}
                            onClick={() => {
                              setChangingScene(isChanging ? null : scene.scene_id);
                              if (!isChanging) setSearchResults(prev => ({ ...prev, [scene.scene_id]: [] }));
                            }}
                          >
                            {soundUrl ? "Change" : "Add"}
                          </Button>
                        </div>

                        {/* Inline search for this scene */}
                        {isChanging && (
                          <div style={{ marginTop: 8 }}>
                            <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                              <Input
                                size="small"
                                placeholder="Search Freesound..."
                                value={searchQuery[scene.scene_id] || ""}
                                onChange={ev => setSearchQuery(prev => ({
                                  ...prev, [scene.scene_id]: ev.target.value,
                                }))}
                                onPressEnter={() => doSearch(scene.scene_id)}
                              />
                              <Button
                                size="small" type="primary"
                                loading={searching[scene.scene_id]}
                                onClick={() => doSearch(scene.scene_id)}
                              >
                                Search
                              </Button>
                            </div>
                            {results.map((r, ri) => (
                              <div key={r.id} style={{
                                display: "flex", alignItems: "center", gap: 6,
                                padding: "4px 8px", borderRadius: 4, marginBottom: 3,
                                background: "#f9fafb", border: "1px solid #e5e7eb",
                              }}>
                                <Button
                                  size="small" shape="circle"
                                  icon={playingUrl === r.preview_url
                                    ? <PauseCircleOutlined />
                                    : <PlayCircleOutlined />}
                                  onClick={() => playPreview(r.preview_url)}
                                />
                                <Text style={{ flex: 1, fontSize: 12 }}>Sound {ri + 1}</Text>
                                <Button
                                  size="small" type="primary"
                                  onClick={() => doAssignScene(ch.id, scene.scene_id, r, ri)}
                                >
                                  Use
                                </Button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <Button
        type="primary"
        size="large"
        style={{ marginTop: 16, width: "100%" }}
        onClick={onDone}
      >
        Continue to synthesis →
      </Button>
    </div>
  );
}

// ── Step 5: Synthesis progress ────────────────────────────────────────────────

function SynthesisStep({ book, chapterIds, chapters, narratorStyle, engine, onClose }) {
  const [statuses,  setStatuses]  = useState({});
  const pollRef    = useRef(null);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    synthesizeBatch(book, chapterIds, engine, narratorStyle).catch(() =>
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
    } catch {}
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
        {selectedChapters.map((ch) => {
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
          title="All chapters synthesized!"
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

const MODAL_STEPS = ["Analysis", "Voice casting", "Select chapters", "Ambient sound", "Synthesis"];

export default function GenerateModal({ open, book, chapters, onClose }) {
  const [current,       setCurrent]       = useState(0);
  const [error,         setError]         = useState(null);
  const [synthIds,      setSynthIds]      = useState([]);
  const [narratorStyle, setNarratorStyle] = useState("theatrical");
  const [synthEngine,   setSynthEngine]   = useState("elevenlabs");

  useEffect(() => {
    if (!open) return;
    getBook(book).then(r => {
      const steps = {};
      for (const s of r.data.steps) steps[s.step] = s.status;
      const analysisDone = [2, 3, 4, 5, 6].every(n => steps[n] === "done");
      if (analysisDone) setCurrent(1);
      else setCurrent(0);
    }).catch(() => {});
  }, [open]);

  const reset = () => {
    setCurrent(0);
    setError(null);
    setSynthIds([]);
    setNarratorStyle("theatrical");
    setSynthEngine("elevenlabs");
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
      width={700}
      title={
        <Space>
          <SoundOutlined style={{ color: "#5a9dad" }} />
          <span>Generate Audiobook</span>
        </Space>
      }
      destroyOnHidden
    >
      <Steps
        current={current}
        size="small"
        style={{ marginBottom: 28 }}
        items={MODAL_STEPS.map(label => ({ title: label }))}
      />

      {error && (
        <Alert
          type="error"
          title={error}
          closable={{ onClose: () => setError(null) }}
          style={{ marginBottom: 16 }}
        />
      )}

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
          onDone={(ids, style, eng) => {
            setSynthIds(ids);
            setNarratorStyle(style);
            setSynthEngine(eng);
            setCurrent(3);
          }}
        />
      )}

      {current === 3 && (
        <AmbientStep
          book={book}
          chapters={chapters}
          chapterIds={synthIds}
          engine={synthEngine}
          onDone={() => setCurrent(4)}
        />
      )}

      {current === 4 && (
        <SynthesisStep
          book={book}
          chapterIds={synthIds}
          chapters={chapters}
          narratorStyle={narratorStyle}
          engine={synthEngine}
          onClose={handleClose}
        />
      )}
    </Modal>
  );
}