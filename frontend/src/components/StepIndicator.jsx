import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";

const NODE_LABELS = {
  interview: "경험 분석",
  extract_star: "STAR 구조 추출",
  grade_gaps: "완성도 & 빈틈 평가",
  generate_questions: "역질문 생성",
  save_experience: "DB & 벡터 저장",
  company_searcher: "기업 웹 리서치",
  identity_portfolio_loader: "신념·포트폴리오 로드",
  alignment_synthesizer: "신념 3각 매칭",
  save_company_profile: "기업 프로필 저장",
  web_search: "웹 검색",
  summarizer: "클립 요약",
  multi_source_retriever: "Multi-Source RAG 검색",
  drafter: "자소서 1차 초안",
  critic: "면접관 관점 비평",
  refiner: "피드백 반영 퇴고",
  de_ai_humanizer: "De-AI 문체 교정",
  copilot_retriever: "경험·관심사 검색",
  relevance_grader: "자료 충분성 평가",
  web_search_fallback: "Corrective 웹 검색",
  copilot_answer: "코파일럿 답변 생성",
  load_retro_context: "포트폴리오·이력 로드",
  analyze_gap_and_plan: "Gap 분석 & 보완 플랜",
  save_application_log: "회고 기록 저장",
};

export default function StepIndicator({ steps }) {
  if (!steps || steps.length === 0) return null;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-2.5">
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">
        LangGraph 실시간 실행 단계
      </div>
      <div className="space-y-2">
        {steps.map((step, idx) => (
          <div
            key={`${step.node}-${idx}`}
            className="flex items-start gap-2.5 text-sm"
          >
            {step.status === "running" && (
              <Loader2 className="w-4 h-4 mt-0.5 text-blue-600 animate-spin shrink-0" />
            )}
            {step.status === "done" && (
              <CheckCircle2 className="w-4 h-4 mt-0.5 text-emerald-600 shrink-0" />
            )}
            {step.status === "error" && (
              <AlertCircle className="w-4 h-4 mt-0.5 text-red-600 shrink-0" />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-slate-800">
                  {NODE_LABELS[step.node] || step.node}
                </span>
                {step.badge && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
                    {step.badge}
                  </span>
                )}
              </div>
              {step.message && (
                <p className="text-xs text-slate-500 mt-0.5 break-words">
                  {step.message}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
