import { useEffect, useState } from "react";
import {
  BookOpen,
  Check,
  Copy,
  Plus,
  Sparkles,
  Trash2,
  Wand2,
} from "lucide-react";
import { api } from "../api/client.js";
import StepIndicator from "../components/StepIndicator.jsx";

export default function CoverLetterStudioPage() {
  const [companies, setCompanies] = useState([]);
  const [selectedCompanyId, setSelectedCompanyId] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [targetRole, setTargetRole] = useState("");
  const [question, setQuestion] = useState("");
  const [charLimit, setCharLimit] = useState(800);
  const [extraInstructions, setExtraInstructions] = useState("");

  const [steps, setSteps] = useState([]);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [copied, setCopied] = useState(false);

  // User's own cover letter reference manager
  const [samples, setSamples] = useState([]);
  const [showSampleForm, setShowSampleForm] = useState(false);
  const [sampleForm, setSampleForm] = useState({
    role_category: "백엔드 / AI",
    question_type: "지원동기",
    structure_pattern: "",
    sample_text: "",
  });
  const [savingSample, setSavingSample] = useState(false);

  const loadInitial = async () => {
    try {
      const [comps, smps] = await Promise.all([
        api.listCompanies(),
        api.listSamples(),
      ]);
      setCompanies(comps || []);
      setSamples(smps || []);
    } catch (err) {
      console.warn(err);
    }
  };

  useEffect(() => {
    loadInitial();
  }, []);

  const handleSelectCompany = (idStr) => {
    setSelectedCompanyId(idStr);
    const found = companies.find((c) => String(c.id) === idStr);
    if (found) {
      setCompanyName(found.company_name);
      if (found.target_role) setTargetRole(found.target_role);
    }
  };

  const handleGenerate = async (e) => {
    e.preventDefault();
    if (!companyName.trim() || !question.trim() || running) return;

    setRunning(true);
    setSteps([]);
    setResult(null);
    setCopied(false);

    try {
      await api.generateCoverLetter(
        {
          company_name: companyName.trim(),
          company_profile_id: selectedCompanyId ? Number(selectedCompanyId) : null,
          target_role: targetRole.trim(),
          question: question.trim(),
          char_limit: Number(charLimit) || 800,
          extra_instructions: extraInstructions.trim(),
        },
        (ev) => {
          if (ev.event === "node_start") {
            setSteps((prev) => [
              ...prev,
              { node: ev.node, status: "running", message: ev.message },
            ]);
          } else if (ev.event === "node_end") {
            setSteps((prev) => {
              const next = [...prev];
              for (let i = next.length - 1; i >= 0; i -= 1) {
                if (next[i].node === ev.node || next[i].status === "running") {
                  let badge;
                  if (ev.node === "critic" && ev.data?.score !== undefined) {
                    badge = `${ev.data.score}점`;
                  } else if (ev.data?.char_count) {
                    badge = `${ev.data.char_count}자`;
                  }
                  next[i] = {
                    ...next[i],
                    node: ev.node,
                    status: "done",
                    badge,
                    message:
                      ev.node === "critic" && ev.data?.feedback
                        ? ev.data.feedback
                        : next[i].message,
                  };
                  break;
                }
              }
              return next;
            });
          } else if (ev.event === "done") {
            setResult(ev.data);
          } else if (ev.event === "error") {
            setSteps((prev) => [
              ...prev,
              { node: "error", status: "error", message: ev.message },
            ]);
          }
        }
      );
    } catch (err) {
      setSteps((prev) => [
        ...prev,
        { node: "error", status: "error", message: err.message },
      ]);
    } finally {
      setRunning(false);
    }
  };

  const handleCopy = async () => {
    if (!result?.final_text) return;
    await navigator.clipboard.writeText(result.final_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleAddSample = async (e) => {
    e.preventDefault();
    if (!sampleForm.sample_text.trim() || savingSample) return;
    setSavingSample(true);
    try {
      await api.createSample({
        role_category: sampleForm.role_category,
        question_type: sampleForm.question_type,
        structure_pattern: sampleForm.structure_pattern,
        sample_text: sampleForm.sample_text,
      });
      setSampleForm({
        role_category: "백엔드 / AI",
        question_type: "지원동기",
        structure_pattern: "",
        sample_text: "",
      });
      setShowSampleForm(false);
      await loadInitial();
    } catch (err) {
      alert(`레퍼런스 저장 실패: ${err.message}`);
    } finally {
      setSavingSample(false);
    }
  };

  const handleDeleteSample = async (refId) => {
    if (!window.confirm("이 자소서 레퍼런스를 삭제할까요?")) return;
    try {
      await api.deleteSample(refId);
      setSamples((prev) => prev.filter((s) => s.ref_id !== refId));
    } catch (err) {
      alert(`삭제 실패: ${err.message}`);
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">
          4. 자소서 공방 (Critic-Refiner-Humanizer)
        </h2>
        <p className="text-sm text-slate-600 mt-1">
          경험·신념·기업 리서치·레퍼런스를 격리 검색해 초안 → 면접관 비평 → 최대 2회 퇴고 → De-AI 문체 교정까지 실시간 실행합니다.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Input Form */}
        <form
          onSubmit={handleGenerate}
          className="lg:col-span-2 rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm"
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">
                리서치된 기업 선택 (선택)
              </span>
              <select
                value={selectedCompanyId}
                onChange={(e) => handleSelectCompany(e.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm bg-white"
              >
                <option value="">직접 입력</option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.company_name} {c.target_role ? `(${c.target_role})` : ""}
                  </option>
                ))}
              </select>
            </label>

            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">기업명 *</span>
              <input
                required
                type="text"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder="예: 네이버, 토스"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">지원 직무</span>
              <input
                type="text"
                value={targetRole}
                onChange={(e) => setTargetRole(e.target.value)}
                placeholder="예: AI 에이전트 백엔드"
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>

            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-700">
                목표 글자 수: {charLimit}자
              </span>
              <input
                type="number"
                min={200}
                max={3000}
                step={50}
                value={charLimit}
                onChange={(e) => setCharLimit(e.target.value)}
                className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>
          </div>

          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">
              자기소개서 문항 *
            </span>
            <textarea
              required
              rows={3}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="예: 지원 동기와 입사 후 기술적으로 기여하고 싶은 바를 본인의 경험을 바탕으로 작성해 주세요."
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-xs font-semibold text-slate-700">
              추가 강조 요청 (선택)
            </span>
            <input
              type="text"
              value={extraInstructions}
              onChange={(e) => setExtraInstructions(e.target.value)}
              placeholder="예: pgvector 격리 설계 경험을 중심 소재로 사용해 주세요."
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
            />
          </label>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={running || !companyName.trim() || !question.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              <Wand2 className="w-4 h-4" />
              <span>{running ? "자소서 생성·퇴고 중..." : "자소서 생성 시작"}</span>
            </button>
          </div>
        </form>

        {/* Live Step Indicator */}
        <div>
          <StepIndicator steps={steps} />
        </div>
      </div>

      {/* Final Output + De-AI Diff Report */}
      {result && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-slate-900">
                  최종 자소서 (De-AI 완료)
                </h3>
                <span className="rounded-full bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">
                  면접관 {result.critic_score}점 · 퇴고 {result.revision_count}회
                </span>
                <span className="text-xs text-slate-500">
                  공백 포함 {(result.final_text || "").length}자
                </span>
              </div>
              <button
                type="button"
                onClick={handleCopy}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                {copied ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-600" />
                    <span>복사됨</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    <span>복사</span>
                  </>
                )}
              </button>
            </div>

            <div className="rounded-xl bg-slate-50 p-4 text-sm text-slate-800 leading-7 whitespace-pre-wrap">
              {result.final_text}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 space-y-4 shadow-sm">
            <h3 className="text-sm font-bold text-slate-900 flex items-center gap-1.5">
              <Sparkles className="w-4 h-4 text-indigo-600" />
              <span>De-AI 변경 리포트 (Diff Summary)</span>
            </h3>
            <ul className="space-y-2 text-xs text-slate-700">
              {(result.diff_summary || []).length === 0 ? (
                <li className="text-slate-400">변경 요약 내역이 없습니다.</li>
              ) : (
                result.diff_summary.map((change, idx) => (
                  <li
                    key={idx}
                    className="rounded-lg bg-indigo-50/60 border border-indigo-100 p-2.5 leading-relaxed"
                  >
                    {change}
                  </li>
                ))
              )}
            </ul>
          </div>
        </div>
      )}

      {/* User's Own Jasoseo Reference Manager */}
      <section className="rounded-2xl border border-slate-200 bg-white p-6 space-y-4 shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <BookOpen className="w-4 h-4" />
              <span>내 합격 자소서 레퍼런스 ({samples.length})</span>
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              직접 수집한 합격 자소서는 Git에 올라가지 않고 로컬/EC2 DB(doc_type=jasoseo_sample)에만 저장되어 전개 구조·설득 논리 참고용으로 사용됩니다.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowSampleForm((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>레퍼런스 직접 등록</span>
          </button>
        </div>

        {showSampleForm && (
          <form
            onSubmit={handleAddSample}
            className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3"
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
              <input
                type="text"
                value={sampleForm.role_category}
                onChange={(e) =>
                  setSampleForm({ ...sampleForm, role_category: e.target.value })
                }
                placeholder="직무군 (예: 백엔드 개발)"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
              />
              <input
                required
                type="text"
                value={sampleForm.question_type}
                onChange={(e) =>
                  setSampleForm({ ...sampleForm, question_type: e.target.value })
                }
                placeholder="문항 유형 * (예: 지원동기, 트러블슈팅)"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
              />
              <input
                type="text"
                value={sampleForm.structure_pattern}
                onChange={(e) =>
                  setSampleForm({
                    ...sampleForm,
                    structure_pattern: e.target.value,
                  })
                }
                placeholder="전개 구조 메모 (선택)"
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
              />
            </div>
            <textarea
              required
              rows={4}
              value={sampleForm.sample_text}
              onChange={(e) =>
                setSampleForm({ ...sampleForm, sample_text: e.target.value })
              }
              placeholder="참고할 합격 자소서 본문을 붙여넣어 주세요 (최소 20자)..."
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowSampleForm(false)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs"
              >
                취소
              </button>
              <button
                type="submit"
                disabled={savingSample}
                className="rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-medium text-white disabled:opacity-50"
              >
                {savingSample ? "임베딩 저장 중..." : "벡터 DB에 저장"}
              </button>
            </div>
          </form>
        )}

        {samples.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {samples.map((s) => (
              <div
                key={s.ref_id}
                className="rounded-xl border border-slate-200 p-3.5 space-y-1.5 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <span className="rounded bg-slate-100 px-2 py-0.5 font-semibold text-slate-700">
                      {s.role_category}
                    </span>
                    <span className="rounded bg-blue-50 px-2 py-0.5 font-medium text-blue-800">
                      {s.question_type}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDeleteSample(s.ref_id)}
                    className="text-slate-400 hover:text-red-600"
                    title="삭제"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
                <p className="text-slate-600 line-clamp-3 leading-relaxed">
                  {s.sample_text}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
