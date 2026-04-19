import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Spin, Typography, Slider, Button, Tooltip, message, Tag } from "antd";
import {
  ArrowLeftOutlined, LeftOutlined, RightOutlined,
  PlayCircleOutlined, PauseCircleOutlined,
  SoundOutlined, UserOutlined, CloudOutlined,
  BulbOutlined, BulbFilled,
} from "@ant-design/icons";
import { getChapterReader, getBook, getAudioUrl, getAmbientConfig, generateAmbient } from "../api/client";

const { Title, Text } = Typography;

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];

const SPEAKER_PALETTE = [
  { bg: "#fef3c7", border: "#fbbf24", text: "#92400e" },
  { bg: "#dbeafe", border: "#60a5fa", text: "#1e40af" },
  { bg: "#fce7f3", border: "#f472b6", text: "#9d174d" },
  { bg: "#d1fae5", border: "#34d399", text: "#065f46" },
  { bg: "transparent", border: "#7bb8c4", text: "#1a4a54" },
  { bg: "#fee2e2", border: "#f87171", text: "#991b1b" },
  { bg: "#e0f2fe", border: "#38bdf8", text: "#0c4a6e" },
  { bg: "#fef9c3", border: "#facc15", text: "#713f12" },
];

function useSpeakerColors(paragraphs) {
  const map = {};
  let idx = 0;
  for (const p of paragraphs) {
    if (p.speaker && !(p.speaker in map)) {
      map[p.speaker] = SPEAKER_PALETTE[idx % SPEAKER_PALETTE.length];
      idx++;
    }
  }
  return map;
}

function formatTime(sec) {
  if (!isFinite(sec)) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function ChapterPage() {
  const { book, chapterId } = useParams();
  const navigate            = useNavigate();

  // Data
  const [chapter,    setChapter]    = useState(null);
  const [bookData,   setBookData]   = useState(null);
  const [paragraphs, setParagraphs] = useState([]);   // raw paras with {index,text,start,end}
  const [loading,    setLoading]    = useState(true);
  const [hasAudio,   setHasAudio]   = useState(false);

  // Player state
  const [playing,    setPlaying]    = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration,   setDuration]   = useState(0);
  const [volume,     setVolume]     = useState(1);
  const [speed,      setSpeed]      = useState(1);
  const [activeIdx,  setActiveIdx]  = useState(null);

  const [showAttribution, setShowAttribution] = useState(false);
  const [darkMode,        setDarkMode]        = useState(false);

  // Ambient
  const [ambientScenes,  setAmbientScenes]  = useState([]);
  const [ambientVolume,  setAmbientVolume]  = useState(0.15);
  const [ambientStatus,  setAmbientStatus]  = useState("none"); // none|running|done|error
  const [ambientEnabled, setAmbientEnabled] = useState(true);
  const ambientRef      = useRef(null);
  const ambientSceneIdx = useRef(-1);

  const audioRef   = useRef(null);
  const paraRefs   = useRef({});
  const scrolledTo = useRef(null);

  // ── Load data ────────────────────────────────────────────────────────────────

  useEffect(() => {
    setLoading(true);
    setPlaying(false);
    setCurrentTime(0);
    setActiveIdx(null);
    scrolledTo.current = null;

    const chData_ref = { current: null };

    getBook(book)
      .then(bRes => {
        setBookData(bRes.data);
        const chData = bRes.data.chapters?.find(c => String(c.id) === String(chapterId));
        chData_ref.current = chData;
        setHasAudio(chData?.synth_status === "done");
        const engine = chData?.synth_engine || "elevenlabs";
        return getChapterReader(book, chapterId, engine);
      })
      .then(rRes => {
        setChapter({ id: rRes.data.id, title: rRes.data.title });
        setParagraphs(rRes.data.paragraphs);
        const engine = chData_ref.current?.synth_engine || "elevenlabs";
        return getAmbientConfig(book, chapterId, engine);
      })
      .then(aRes => {
        setAmbientStatus(aRes.data.status);
        setAmbientScenes(aRes.data.scenes ?? []);
      })
      .catch(() => message.error("Failed to load chapter"))
      .finally(() => setLoading(false));
  }, [book, chapterId]);

  // ── Audio element setup ──────────────────────────────────────────────────────

  useEffect(() => {
    if (!hasAudio) return;
    const chData = bookData?.chapters?.find(c => String(c.id) === String(chapterId));
    const engine = chData?.synth_engine || "elevenlabs";
    const audio  = new Audio(getAudioUrl(book, chapterId, engine));
    audioRef.current = audio;

    audio.playbackRate = speed;
    audio.volume       = volume;

    audio.addEventListener("timeupdate", () => setCurrentTime(audio.currentTime));
    audio.addEventListener("durationchange", () => setDuration(audio.duration));
    audio.addEventListener("ended", () => setPlaying(false));
    audio.addEventListener("error",  () => setHasAudio(false));

    return () => {
      audio.pause();
      audio.src = "";
      if (ambientRef.current) { ambientRef.current.pause(); ambientRef.current = null; }
      ambientSceneIdx.current = -1;
    };
  }, [hasAudio, book, chapterId]);

  // ── Ambient: switch scene sound based on currentTime ────────────────────────

  useEffect(() => {
    if (!ambientScenes.length || !playing || !ambientEnabled) return;

    const sceneIdx = ambientScenes.findIndex(
      s => s.start != null && s.end != null && currentTime >= s.start && currentTime < s.end
    );

    if (sceneIdx === ambientSceneIdx.current) return;
    ambientSceneIdx.current = sceneIdx;

    // Stop previous
    if (ambientRef.current) {
      ambientRef.current.pause();
      ambientRef.current = null;
    }

    const scene = ambientScenes[sceneIdx];
    if (!scene?.sound_url) return;

    const a = new Audio(`http://localhost:8000${scene.sound_url}`);
    a.volume = ambientVolume;
    a.loop   = true;
    a.play().catch(() => {});
    ambientRef.current = a;
  }, [currentTime, ambientScenes, playing]);

  // Stop ambient when speech paused or ambient disabled
  useEffect(() => {
    if (!ambientRef.current) return;
    if (playing && ambientEnabled) ambientRef.current.play().catch(() => {});
    else                           ambientRef.current.pause();
  }, [playing, ambientEnabled]);

  // When ambient disabled — reset scene so it restarts fresh when re-enabled
  useEffect(() => {
    if (!ambientEnabled && ambientRef.current) {
      ambientRef.current.pause();
      ambientRef.current = null;
      ambientSceneIdx.current = -1;
    }
  }, [ambientEnabled]);

  // Sync ambient volume
  useEffect(() => {
    if (ambientRef.current) ambientRef.current.volume = ambientVolume;
  }, [ambientVolume]);

  // ── Sync speed / volume to audio element ────────────────────────────────────

  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = speed;
  }, [speed]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = volume;
  }, [volume]);

  // ── Highlight current paragraph from embedded timestamps ────────────────────

  useEffect(() => {
    if (!paragraphs.length) return;
    const para = paragraphs.find(p => p.start != null && currentTime >= p.start && currentTime < p.end);
    const idx  = para ? para.index : null;
    if (idx === activeIdx) return;
    setActiveIdx(idx);

    if (idx !== null && idx !== scrolledTo.current && paraRefs.current[idx]) {
      scrolledTo.current = idx;
      paraRefs.current[idx].scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [currentTime, paragraphs]);

  // ── Player controls ──────────────────────────────────────────────────────────

  const togglePlay = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing) { audio.pause(); setPlaying(false); }
    else          { audio.play();  setPlaying(true);  }
  }, [playing]);

  const seek = useCallback((sec) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = Math.max(0, Math.min(audio.duration || 0, sec));
  }, []);

  const handleSeekBar = useCallback((val) => seek(val), [seek]);

  const handleParaClick = useCallback((paraIdx) => {
    const para = paragraphs.find(p => p.index === paraIdx);
    if (para?.start != null) {
      seek(para.start);
      if (!playing && audioRef.current) { audioRef.current.play(); setPlaying(true); }
    }
  }, [paragraphs, playing, seek]);

  const cycleSpeed = () => {
    const next = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length];
    setSpeed(next);
  };

  // ── Chapter navigation ───────────────────────────────────────────────────────

  const chapters      = bookData?.chapters ?? [];
  const currentIdx    = chapters.findIndex(c => String(c.id) === String(chapterId));
  const prev          = chapters[currentIdx - 1];
  const next_ch       = chapters[currentIdx + 1];
  const speakerColors = useSpeakerColors(paragraphs);

  // ── Keyboard shortcuts ───────────────────────────────────────────────────────

  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (e.code === "Space")       { e.preventDefault(); togglePlay(); }
      if (e.code === "ArrowLeft")   seek(currentTime - 5);
      if (e.code === "ArrowRight")  seek(currentTime + 5);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [togglePlay, seek, currentTime]);

  // ── Render ───────────────────────────────────────────────────────────────────

  if (loading) return (
    <div style={{ textAlign: "center", paddingTop: 120 }}><Spin size="large" /></div>
  );
  if (!chapter) return (
    <div style={{ textAlign: "center", paddingTop: 120 }}>
      <Text type="secondary">Chapter not found</Text>
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden",
                  background: darkMode ? "#0f0f0f" : "#fafaf8",
                  transition: "background 0.3s" }}>

      {/* ── Top bar ── */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "14px 24px", borderBottom: `1px solid ${darkMode ? "#2a2a2a" : "#e5e7eb"}`,
        background: darkMode ? "#1a1a1a" : "#fff", flexShrink: 0,
        transition: "background 0.3s",
      }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/books/${book}`)}>
          {bookData?.title ?? "Back"}
        </Button>
        <div style={{ flex: 1, textAlign: "center" }}>
          <Text strong style={{ fontSize: 15, color: darkMode ? "#e5e7eb" : "#111827" }}>{chapter.title}</Text>
        </div>
        <Tooltip title={darkMode ? "Light mode" : "Dark mode"}>
          <Button
            size="small"
            icon={darkMode ? <BulbFilled /> : <BulbOutlined />}
            type={darkMode ? "primary" : "default"}
            onClick={() => setDarkMode(v => !v)}
          />
        </Tooltip>

        <Tooltip title={showAttribution ? "Hide speaker attribution" : "Show speaker attribution"}>
          <Button
            size="small"
            icon={<UserOutlined />}
            type={showAttribution ? "primary" : "default"}
            onClick={() => setShowAttribution(v => !v)}
          >
            Attribution
          </Button>
        </Tooltip>

        {/* Ambient button */}
        {hasAudio && (() => {
          const hasSound = ambientScenes.some(s => s.sound_url);
          if (ambientStatus === "running") return (
            <Button size="small" loading disabled>Generating...</Button>
          );
          if (ambientStatus === "done" && hasSound) return (
            <Tooltip title={ambientEnabled ? "Disable ambient sounds" : "Enable ambient sounds"}>
              <Button
                size="small"
                icon={<CloudOutlined />}
                type={ambientEnabled ? "primary" : "default"}
                style={ambientEnabled ? { background: "#059669", borderColor: "#059669" } : {}}
                onClick={() => setAmbientEnabled(v => !v)}
              >
                Ambient
              </Button>
            </Tooltip>
          );
          return (
            <Tooltip title="Generate ambient background sounds for each scene">
              <Button
                size="small"
                icon={<CloudOutlined />}
                onClick={async () => {
                  const chData = bookData?.chapters?.find(c => String(c.id) === String(chapterId));
                  const engine = chData?.synth_engine || "elevenlabs";
                  setAmbientStatus("running");
                  try {
                    await generateAmbient(book, chapterId, engine);
                    const poll = setInterval(async () => {
                      const r = await getAmbientConfig(book, chapterId, engine);
                      if (r.data.status === "done") {
                        clearInterval(poll);
                        setAmbientStatus("done");
                        setAmbientScenes(r.data.scenes ?? []);
                      } else if (r.data.status === "error") {
                        clearInterval(poll);
                        setAmbientStatus("error");
                      }
                    }, 3000);
                  } catch { setAmbientStatus("error"); }
                }}
              >
                Add ambient
              </Button>
            </Tooltip>
          );
        })()}
        <Button
          icon={<LeftOutlined />}
          size="small"
          disabled={!prev}
          onClick={() => navigate(`/books/${book}/chapters/${prev.id}`)}
        />
        <Button
          icon={<RightOutlined />}
          size="small"
          disabled={!next_ch}
          onClick={() => navigate(`/books/${book}/chapters/${next_ch.id}`)}
        />
      </div>

      {/* ── Text scroll area ── */}
      <div style={{ flex: 1, overflowY: "auto", padding: "40px 0",
                    transition: "background 0.3s" }}>
        <div style={{ maxWidth: 680, margin: "0 auto", padding: "0 24px" }}>
          {paragraphs.map((para) => {
            const isActive   = activeIdx === para.index;
            const clickable  = para.start != null;
            const isDialogue = para.type === "dialogue" && para.speaker;
            const color      = isDialogue ? speakerColors[para.speaker] : null;

            const activeColor = isActive && showAttribution && color;

            const defaultText = darkMode ? "#d1d5db" : "#374151";
            const textColor   = activeColor ? color.text : isActive ? (darkMode ? "#c7d2fe" : "#1e1b4b") : defaultText;
            const activeBg     = activeColor ? color.bg     : isActive ? (darkMode ? "#1e1b4b" : "#eef2ff") : undefined;
            const activeBorder = activeColor ? `2px solid ${color.border}` : isActive ? "2px solid #5a9dad" : undefined;

            return (
              <div
                key={para.index}
                ref={el => { paraRefs.current[para.index] = el; }}
                onClick={() => handleParaClick(para.index)}
                style={{
                  display:     "flex",
                  alignItems:  "flex-start",
                  gap:         12,
                  marginBottom: para.type === "dialogue" ? 8 : 20,
                  cursor:      clickable ? "pointer" : "default",
                }}
              >
                <p style={{ flex: 1, margin: 0, fontSize: 18, lineHeight: 1.9, color: defaultText }}>
                  <span
                    style={{
                      color:        textColor,
                      background:   activeBg,
                      border:       activeBorder,
                      borderRadius: 6,
                      padding:      isActive ? "2px 8px" : "0",
                      transition:   "background 0.2s, color 0.15s",
                      display:      "inline",
                    }}
                  >
                    {para.text}
                  </span>
                  {showAttribution && isDialogue && isActive && (
                    <span
                      style={{
                        display:      "inline",
                        background:   activeColor ? color.bg : "#eef2ff",
                        border:       activeColor ? `2px solid ${color.border}` : "2px solid #5a9dad",
                        borderRadius: 6,
                        padding:      "2px 8px",
                        marginLeft:   8,
                        color:        activeColor ? color.text : "#1e1b4b",
                        fontSize:     13,
                        fontWeight:   600,
                        whiteSpace:   "nowrap",
                        verticalAlign: "middle",
                      }}
                    >
                      {para.speaker}
                    </span>
                  )}
                </p>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Player bar ── */}
      <div style={{
        background: "#5a9dad", color: "#fff",
        padding: "14px 24px 18px", flexShrink: 0,
        boxShadow: "0 -4px 20px rgba(0,0,0,0.12)",
      }}>
        {!hasAudio && (
          <div style={{ textAlign: "center", marginBottom: 10 }}>
            <Text style={{ color: "rgba(255,255,255,0.75)", fontSize: 12 }}>
              Audio not synthesized yet. Use Generate Audiobook to create it.
            </Text>
          </div>
        )}

        {/* Seek bar */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
          <Text style={{ color: "#c8e6ee", fontSize: 12, width: 38, flexShrink: 0 }}>
            {formatTime(currentTime)}
          </Text>
          <Slider
            min={0} max={duration || 1} step={0.5}
            value={currentTime}
            onChange={handleSeekBar}
            disabled={!hasAudio}
            tooltip={{ formatter: (v) => formatTime(v) }}
            style={{ flex: 1, margin: 0 }}
            styles={{ track: { background: "rgba(255,255,255,0.9)" }, handle: { borderColor: "#fff", background: "#fff" } }}
          />
          <Text style={{ color: "#c8e6ee", fontSize: 12, width: 38, flexShrink: 0, textAlign: "right" }}>
            {formatTime(duration)}
          </Text>
        </div>

        {/* Controls */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, paddingLeft: 60 }}>

          {/* -5s */}
          <Tooltip title="−5 sec  (←)">
            <Button
              type="text" shape="circle"
              disabled={!hasAudio}
              icon={<span style={{ fontSize: 13, color: hasAudio ? "#c8e6ee" : "#7fb3bf" }}>−5</span>}
              onClick={() => seek(currentTime - 5)}
            />
          </Tooltip>

          {/* Play / Pause */}
          <Button
            type="text" shape="circle"
            disabled={!hasAudio}
            icon={playing
              ? <PauseCircleOutlined style={{ fontSize: 40, color: hasAudio ? "#fff" : "#7fb3bf" }} />
              : <PlayCircleOutlined  style={{ fontSize: 40, color: hasAudio ? "#fff" : "#7fb3bf" }} />
            }
            onClick={togglePlay}
            style={{ display: "flex", alignItems: "center", justifyContent: "center" }}
          />

          {/* +5s */}
          <Tooltip title="+5 sec  (→)">
            <Button
              type="text" shape="circle"
              disabled={!hasAudio}
              icon={<span style={{ fontSize: 13, color: hasAudio ? "#c8e6ee" : "#7fb3bf" }}>+5</span>}
              onClick={() => seek(currentTime + 5)}
            />
          </Tooltip>

          {/* Speed */}
          <Tooltip title="Playback speed">
            <Button
              type="text"
              disabled={!hasAudio}
              onClick={cycleSpeed}
              style={{
                color: hasAudio ? "#c8e6ee" : "#7fb3bf", fontWeight: 600, fontSize: 13,
                minWidth: 44, padding: "0 8px",
              }}
            >
              {speed}×
            </Button>
          </Tooltip>

          {/* Volume */}
          <SoundOutlined style={{ color: hasAudio ? "#c8e6ee" : "#7fb3bf", fontSize: 14 }} />
          <Slider
            min={0} max={1} step={0.05}
            value={volume}
            onChange={setVolume}
            disabled={!hasAudio}
            style={{ width: 80, margin: 0 }}
            tooltip={{ formatter: v => `${Math.round(v * 100)}%` }}
            styles={{ track: { background: "rgba(255,255,255,0.9)" }, handle: { borderColor: "#fff", background: "#fff" } }}
          />

          {/* Ambient volume */}
          {ambientEnabled && ambientStatus === "done" && ambientScenes.some(s => s.sound_url) && (
            <div style={{ display: "flex", alignItems: "center", gap: 8,
                          borderLeft: "1px solid #4a8a9a", paddingLeft: 8 }}>
              <CloudOutlined style={{ color: "#34d399", fontSize: 14 }} />
              <Slider
                min={0} max={0.30} step={0.01}
                value={ambientVolume}
                onChange={v => setAmbientVolume(v)}
                style={{ width: 70, margin: 0 }}
                tooltip={{ formatter: v => `${Math.round((v / 0.30) * 100)}%` }}
                styles={{ track: { background: "#34d399" }, handle: { borderColor: "#34d399" } }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}