import React, { useState, useEffect, useRef } from 'react';
import { Upload, CheckCircle2, XCircle, Sparkles, ChevronDown, ChevronUp, Target, Lightbulb, BadgeCheck, ArrowRight, Loader2, FileText, Download, Trophy, Flame } from 'lucide-react';

// --- CONSTANTS & DATA ---
const apiKey = ""; // Gemini API key provided by the Canvas environment

// Dr. Reflex Mascot SVG
const MASCOT_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">
  <defs>
    <radialGradient id="bg" cx="50%" cy="50%" r="50%" fx="50%" fy="50%">
      <stop offset="0%" stop-color="#e0f2fe" />
      <stop offset="100%" stop-color="#bae6fd" />
    </radialGradient>
  </defs>
  <circle cx="100" cy="100" r="100" fill="url(#bg)"/>
  <path d="M 50 200 L 50 120 C 50 90, 150 90, 150 120 L 150 200 Z" fill="#ffffff" stroke="#94a3b8" stroke-width="4"/>
  <path d="M 80 120 L 100 150 L 120 120" fill="none" stroke="#cbd5e1" stroke-width="4"/>
  <path d="M 95 150 L 105 150 L 100 180 Z" fill="#38bdf8"/>
  <circle cx="100" cy="70" r="35" fill="#fef08a" stroke="#eab308" stroke-width="3"/>
  <circle cx="85" cy="65" r="12" fill="#ffffff" stroke="#1e293b" stroke-width="3"/>
  <circle cx="115" cy="65" r="12" fill="#ffffff" stroke="#1e293b" stroke-width="3"/>
  <path d="M 97 65 L 103 65" fill="none" stroke="#1e293b" stroke-width="3"/>
  <path d="M 73 65 C 60 65, 55 70, 55 80" fill="none" stroke="#1e293b" stroke-width="3"/>
  <path d="M 127 65 C 140 65, 145 70, 145 80" fill="none" stroke="#1e293b" stroke-width="3"/>
  <circle cx="85" cy="65" r="4" fill="#0f172a"/>
  <circle cx="115" cy="65" r="4" fill="#0f172a"/>
  <path d="M 85 80 Q 100 95 115 80" fill="none" stroke="#0f172a" stroke-width="3" stroke-linecap="round"/>
  <path d="M 65 120 C 50 160, 150 160, 135 120" fill="none" stroke="#334155" stroke-width="5"/>
  <circle cx="125" cy="148" r="8" fill="#334155"/>
  <circle cx="125" cy="148" r="4" fill="#cbd5e1"/>
  <path d="M 150 140 Q 170 140 170 110" fill="none" stroke="#ffffff" stroke-width="16" stroke-linecap="round"/>
  <path d="M 150 140 Q 170 140 170 110" fill="none" stroke="#94a3b8" stroke-width="16" stroke-linecap="round" stroke-dasharray="0 40 40 0"/>
  <circle cx="170" cy="105" r="12" fill="#fef08a" stroke="#eab308" stroke-width="2"/>
  <line x1="170" y1="115" x2="170" y2="60" stroke="#94a3b8" stroke-width="6" stroke-linecap="round"/>
  <path d="M 155 60 Q 170 45 185 60 L 180 65 L 160 65 Z" fill="#ef4444"/>
  <circle cx="170" cy="63" r="3" fill="#cbd5e1"/>
</svg>`;
const MASCOT_IMG = `data:image/svg+xml;utf8,${encodeURIComponent(MASCOT_SVG)}`;

const bloomLevels = [
  { level: 6, name: 'Create', color: 'text-amber-500', description: 'Produce new or original work' },
  { level: 5, name: 'Evaluate', color: 'text-orange-500', description: 'Justify a stand or decision' },
  { level: 4, name: 'Analyze', color: 'text-red-500', description: 'Draw connections among ideas' },
  { level: 3, name: 'Apply', color: 'text-green-500', description: 'Use information in new situations' },
  { level: 2, name: 'Understand', color: 'text-cyan-500', description: 'Explain ideas or concepts' },
  { level: 1, name: 'Remember', color: 'text-blue-500', description: 'Recall facts and basic concepts' }
];

const QUESTIONS = [
  {
    id: 1,
    type: 'key-idea',
    title: 'Q1: The Key Idea',
    objective: 'Test understanding of mechanisms or key findings.',
    gradient: 'from-cyan-400 to-cyan-500',
    headerColor: 'bg-cyan-500',
    guidance: {
      objective: "Create a question whose answer requires synthesizing key mechanisms or findings.",
      lookingFor: "Write a SHORT question (1-2 sentences) that someone can answer correctly if they understand the article's key concepts. Think: exam question style.",
      criteria: ["Requires applying or synthesizing article concepts", "Cannot be answered by copying a single sentence from the paper", "Forces the answerer to demonstrate true understanding", "Short and specific (like an exam question)"],
      failures: ["\"What was the main finding?\" (Can be answered by skimming)", "\"Summarize the results\" (Level 2 - just restating)", "\"List three mechanisms\" (Level 1 - just recall)"],
      example: "In a patient with mechanism A impairment and mechanism B overactivity (both discussed in the article), which intervention would likely be most effective and why?"
    }
  },
  {
    id: 2,
    type: 'clinical-case',
    title: 'Q2: The Clinical Case',
    objective: 'Test application to a specific patient scenario.',
    gradient: 'from-green-400 to-green-500',
    headerColor: 'bg-green-500',
    guidance: {
      objective: "Create a clinical scenario that requires applying article findings to a specific patient.",
      lookingFor: "Write a short clinical vignette (board-exam style) featuring a specific patient. The question must force the learner to use the article's findings to make a clinical decision, diagnosis, or treatment plan for THIS patient.",
      criteria: ["MUST include specific patient details (age, sex, presentation)", "Requires applying the article's concepts to a new/hypothetical scenario", "Cannot be answered without understanding the paper's clinical implications", "Short and specific (like an exam question)"],
      failures: ["\"How would you treat a patient with this disease?\" (Too generic)", "\"What did the study say about treatment?\" (No specific patient)", "\"Is Drug X safe for a 45-year-old?\" (If the article explicitly states this - no synthesis)"],
      example: "A 54-year-old female presents with symptoms consistent with the cohort in the study. Given her concurrent use of Medication Y, how should her dosage of the experimental drug be adjusted?"
    }
  },
  {
    id: 3,
    type: 'limitation',
    title: 'Q3: The Limitation',
    objective: 'Test understanding of study design flaws.',
    gradient: 'from-purple-400 to-purple-500',
    headerColor: 'bg-purple-500',
    guidance: {
      objective: "Create a question that evaluates the study's design flaws and how they impact conclusions.",
      lookingFor: "Write a specific question about a methodological weakness of THIS particular study. It must require the learner to demonstrate they understand the methods used and how a specific flaw limits the real-world application of the findings.",
      criteria: ["Focuses on a specific methodological choice in THIS paper", "Requires analyzing how that choice biases or limits the results", "Forces the answerer to evaluate the strength of the evidence", "Short and specific (like an exam question)"],
      failures: ["\"What are the limitations of this study?\" (Too generic, allows copy-pasting the limitations section)", "\"Did the study have a large enough sample size?\" (Can be answered with a simple yes/no)", "\"Why is a retrospective design bad?\" (General knowledge, not specific to this article)"],
      example: "The authors chose to use Assessment Tool X rather than the gold-standard Tool Y. How might this specific choice have skewed the primary outcome measures reported in Table 2?"
    }
  }
];

// --- UTILS & SOUND ---
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

const formatTime = (seconds) => {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
};

const playSound = (type) => {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext();
    const playOscillator = (freq, type, startTime, duration) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(freq, ctx.currentTime + startTime);
      gain.gain.setValueAtTime(0, ctx.currentTime + startTime);
      gain.gain.linearRampToValueAtTime(0.3, ctx.currentTime + startTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + startTime + duration);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + startTime);
      osc.stop(ctx.currentTime + startTime + duration);
    };

    if (type === 'success') {
      playOscillator(783.99, 'sine', 0, 0.15);
      playOscillator(1046.50, 'sine', 0.1, 0.4);
    } else if (type === 'error') {
      playOscillator(349.23, 'triangle', 0, 0.2);
      playOscillator(311.13, 'triangle', 0.2, 0.3);
    } else if (type === 'complete') {
      playOscillator(523.25, 'square', 0, 0.15);
      playOscillator(659.25, 'square', 0.15, 0.15);
      playOscillator(783.99, 'square', 0.3, 0.15);
      playOscillator(1046.50, 'square', 0.45, 0.6);
    }
  } catch (e) {
    console.warn("Audio play failed or blocked", e);
  }
};

const getXP = (level) => {
  if (level < 3) return 0;
  if (level === 3) return 100;
  if (level === 4) return 150;
  if (level === 5) return 200;
  if (level === 6) return 300;
  return 0;
};

const getRank = (xp) => {
  if (xp >= 800) return "Bloomer Legend";
  if (xp >= 550) return "Master Scholar";
  if (xp >= 350) return "Advanced Thinker";
  return "Capable Learner";
};

// --- LLM ---
async function evaluateWithGemini(questionText, pdfBase64, qType) {
  const qTypeRules = qType === 'key-idea' 
  ? `Q1 (KEY-IDEA) - Tests understanding of mechanisms/findings\nREQUIREMENTS:\n✓ About scientific concepts, mechanisms, or key findings\n✓ Answerable in 1-3 sentences or multiple choice format\n✓ Shows genuine engagement with at least one key concept from the article\n✓ Short and specific (exam question style)\n✓ Connecting multiple ideas is great, but a strong question about ONE key concept is also acceptable\n✓ Clinical or patient scenarios ARE FULLY ALLOWED and welcomed if they test the core mechanism/finding.\nAUTOMATIC FAIL:\n✗ About methodology/limitations → That's Q3, not Q1\n✗ Asks to "design" or "create" something → Too meta\n✗ So shallow it could be answered without reading the article`
  : qType === 'clinical-case'
  ? `Q2 (CLINICAL-CASE) - Tests application to a specific patient\nREQUIREMENTS:\n✓ MUST have specific patient (age, sex, clinical details)\n✓ Answerable question about this patient\n✓ Answering requires applying article findings to this specific case\n✓ Short and focused (exam question style)\nAUTOMATIC FAIL:\n✗ No specific patient → Too generic, not Q2\n✗ About mechanisms without a patient → That's Q1, not Q2\n✗ About methodology → That's Q3, not Q2\n✗ Clinical data contradicts article's criteria\n✗ Asks to "create" or "formulate" something → Too meta/open-ended`
  : `Q3 (LIMITATION) - Tests understanding of study design flaws\nREQUIREMENTS:\n✓ About THIS study's methodology, design, or limitations\n✓ Answerable question about how limitations affect conclusions\n✓ Requires article-specific knowledge\n✓ Short and focused (exam question style)\nAUTOMATIC FAIL:\n✗ About clinical management → That's Q1 or Q2, not Q3\n✗ Generic "What are limitations?" → Too broad\n✗ Asks to "design" or "propose" alternatives → Too meta`;

  const systemPrompt = `You are a supportive medical education tutor assessing a LEARNER'S depth of understanding of a research article — based on the quality of a question they wrote.

CORE PRINCIPLE: The question is a window into the learner's mind. A learner who deeply understands the article will naturally write questions that require synthesizing multiple concepts. A learner who only skimmed the surface will write shallow or generic questions. You are grading the LEARNER'S understanding, not the question itself.

INTERNAL EVALUATION (do NOT expose to the learner):
- Try to answer the learner's question using ONLY the article content
- Does the question show the learner engaged with SPECIFIC content from THIS article?
- Or does it suggest the learner could have written this without actually reading the article?

=== MOST IMPORTANT RULE — ANTI-CHEATING ===
Your feedback and suggestions are the ONLY thing the learner sees. If you include ANY specific content from the article, the learner can simply copy-paste your words into the question box and pass without learning anything. This completely defeats the purpose of the tool.

ABSOLUTE PROHIBITIONS in feedback and suggestions:
- NEVER mention any drug names, gene names, protein names, or biomarkers from the article
- NEVER mention any specific numbers, statistics, p-values, sample sizes, or percentages
- NEVER mention any specific patient populations, conditions, or outcomes described in the article
- NEVER mention specific study methods, instruments, or measures used
- NEVER mention author names or specific referenced studies
- NEVER suggest what a good question WOULD look like — even as an example
- NEVER use phrases like "consider how X relates to Y" where X or Y are from the article
- NEVER say "the article discusses X" or "the study found X"

ALLOWED in feedback and suggestions:
You CAN reference structural or general features of the article to point the learner in the right direction. You CANNOT name the actual findings, drugs, data, mechanisms, or outcomes. The learner should have to go BACK TO THE ARTICLE to act on your advice.

TEST: Before outputting, re-read your feedback and suggestions. Could a learner copy-paste ANY phrase from your output into the question box and get closer to passing? If yes, rewrite it. But also ask: does my feedback give the learner a useful direction to look?

FEEDBACK PRINCIPLE:
- If PASS: Celebrate in general terms. Say what TYPE of thinking they showed without naming specifics.
- If FAIL: Be encouraging. Point them toward a section or angle of the article that could deepen their understanding.
- NEVER say: "your question is generic/article-specific", "evaluation criteria", "detected level".`;

  const promptText = `You have read the article. Now assess this LEARNER'S understanding based on their question.

=== THE LEARNER'S QUESTION ===
"${questionText}"

=== QUESTION TYPE: ${qType} ===
${qTypeRules}

=== YOUR ASSESSMENT PROCESS ===

**STEP 1: WHAT DOES THIS QUESTION REVEAL ABOUT THE LEARNER?**
- Does the question show the learner identified specific concepts, findings, or data from the article?
- Or could someone who never read the article have written this question?

**STEP 2: ASSESS THE LEARNER'S DEPTH OF UNDERSTANDING**
- Level 1-2: Recalling facts or simple restatement → FAIL. Needs deeper engagement.
- Level 3: Can apply knowledge to a new scenario → PASS. Good, meets baseline.
- Level 4: Can analyze connections and structure → PASS. Strong understanding.
- Level 5: Can evaluate, judge, or critique → PASS. Excellent, near mastery.
- Level 6: Can synthesize creatively or produce new original thought → PASS. True mastery.
IMPORTANT EXCEPTION FOR Q1 (key-idea): A well-crafted question about a SINGLE key concept from the article is sufficient for Level 6.

**STEP 3: TYPE MATCHING**
- Q1 (key-idea): About mechanisms/findings.
- Q2 (clinical-case): MUST have specific patient details
- Q3 (limitation): About study methodology
Does it match ${qType}?

**ANTI-CHEATING CHECK (CRITICAL — DO THIS BEFORE OUTPUTTING):**
Re-read your feedback and suggestions. Remove ANY word or phrase that comes from the article. The learner must not be able to copy your output to construct a passing question.

**STATUS RULE**: 
You MUST set "status" to "PASS" if the bloomLevel is 3, 4, 5, or 6. Set to "FAIL" ONLY if the bloomLevel is 1 or 2.`;

  const payload = {
    systemInstruction: { parts: [{ text: systemPrompt }] },
    contents: [{ role: "user", parts: [{ text: promptText }, { inlineData: { mimeType: "application/pdf", data: pdfBase64 } }] }],
    generationConfig: {
      responseMimeType: "application/json",
      responseSchema: {
        type: "OBJECT",
        properties: {
          bloomLevel: { type: "INTEGER", description: "1 to 6" },
          status: { type: "STRING", description: "PASS or FAIL" },
          feedback: { type: "STRING", description: "2-3 sentences of encouragement/guidance" },
          detectedLevel: { type: "STRING", description: "remember, understand, apply, analyze, evaluate, or create" },
          suggestions: { type: "ARRAY", items: { type: "STRING" } }
        },
        required: ["bloomLevel", "status", "feedback", "detectedLevel", "suggestions"]
      }
    }
  };

  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key=${apiKey}`;
  const delays = [1000, 2000, 4000, 8000, 16000];
  for (let i = 0; i < 5; i++) {
    try {
      const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (!response.ok) throw new Error(`HTTP Error: ${response.status}`);
      const data = await response.json();
      return JSON.parse(data.candidates[0].content.parts[0].text);
    } catch (err) {
      if (i === 4) throw err;
      await sleep(delays[i]);
    }
  }
}

// --- MAIN APP COMPONENT ---
export default function App() {
  const [appState, setAppState] = useState('landing'); 
  const [uploadedArticle, setUploadedArticle] = useState(null);
  const [inputs, setInputs] = useState({ 1: '', 2: '', 3: '' });
  const [feedbacks, setFeedbacks] = useState({});
  const [attemptHistory, setAttemptHistory] = useState({ 1: [], 2: [], 3: [] });
  const [currentQuestionId, setCurrentQuestionId] = useState(1);
  const [questionTimes, setQuestionTimes] = useState({ 1: 0, 2: 0, 3: 0 });
  const [evaluating, setEvaluating] = useState(new Set());
  const [collapsedGuidance, setCollapsedGuidance] = useState(new Set([2, 3]));
  const [drawerData, setDrawerData] = useState(null); 
  
  const totalXP = Object.values(feedbacks).reduce((sum, feedback) => sum + getXP(feedback.bloomLevel), 0);
  const passedCount = Object.values(feedbacks).filter(f => f.status === 'PASS').length;

  // Timer
  useEffect(() => {
    let interval;
    if (appState === 'questions' && currentQuestionId <= 3 && !evaluating.has(currentQuestionId) && !drawerData) {
      interval = setInterval(() => {
        setQuestionTimes(prev => ({ ...prev, [currentQuestionId]: prev[currentQuestionId] + 1 }));
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [appState, currentQuestionId, evaluating, drawerData]);

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0];
    if (file && file.type === 'application/pdf') {
      const reader = new FileReader();
      reader.onload = (evt) => {
        setUploadedArticle({
          name: file.name,
          size: (file.size / 1024 / 1024).toFixed(2) + ' MB',
          base64: evt.target.result.split(',')[1]
        });
      };
      reader.readAsDataURL(file);
    }
  };

  const toggleGuidance = (id) => {
    setCollapsedGuidance(prev => {
      const newSet = new Set(prev);
      if (newSet.has(id)) newSet.delete(id); else newSet.add(id);
      return newSet;
    });
  };

  const handleEvaluate = async (qId) => {
    if (!inputs[qId].trim() || !uploadedArticle) return;
    
    setEvaluating(prev => new Set(prev).add(qId));
    
    try {
      const qDef = QUESTIONS.find(q => q.id === qId);
      const result = await evaluateWithGemini(inputs[qId], uploadedArticle.base64, qDef.type);
      
      setAttemptHistory(prev => ({ ...prev, [qId]: [...prev[qId], result.bloomLevel] }));

      const existing = feedbacks[qId];
      const isFirstPass = result.status === 'PASS' && (!existing || existing.status !== 'PASS');
      const isImprovement = existing && result.status === 'PASS' && result.bloomLevel > existing.bloomLevel;

      setFeedbacks(prev => {
        if (!existing || result.bloomLevel > (existing.bloomLevel || 0) || result.status === 'PASS') {
            return { ...prev, [qId]: result };
        }
        return prev;
      });

      if (result.status === 'PASS') { playSound('success'); } else { playSound('error'); }
      setDrawerData({ ...result, qId, isFirstPass, isImprovement });

    } catch (error) {
      alert("An error occurred during evaluation. Please try again.");
      console.error(error);
    } finally {
      setEvaluating(prev => {
        const newSet = new Set(prev);
        newSet.delete(qId);
        return newSet;
      });
    }
  };

  const handleCloseDrawer = () => {
      const { status, qId } = drawerData;
      setDrawerData(null);

      if (status === 'PASS') {
         if (qId < 3 && currentQuestionId === qId) {
             setCurrentQuestionId(qId + 1);
             setCollapsedGuidance(prev => {
                 const newSet = new Set(prev);
                 newSet.add(qId);
                 newSet.delete(qId + 1);
                 return newSet;
             });
         } else if (qId === 3 && passedCount === 3) {
             playSound('complete');
             setAppState('mastery');
         }
      }
  };

  const resetQuestion = (qId) => {
    setFeedbacks(prev => {
      const next = { ...prev };
      delete next[qId];
      return next;
    });
  };

  const generateCertificate = () => {
    const totalTimeInSecs = Object.values(questionTimes).reduce((a, b) => a + b, 0);
    const dateStr = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
    const rankName = getRank(totalXP);
    
    let html = `
      <!DOCTYPE html>
      <html lang="en">
      <head>
        <meta charset="UTF-8">
        <title>Bloomer Mastery Certificate</title>
        <style>
          body { font-family: system-ui, -apple-system, sans-serif; color: #1e293b; max-width: 800px; margin: 0 auto; padding: 40px; }
          .header { display: flex; align-items: center; gap: 24px; border-bottom: 4px solid #e2e8f0; padding-bottom: 32px; margin-bottom: 32px; }
          .header img { width: 100px; height: 100px; border-radius: 50%; background: #e0f2fe; }
          .header h1 { margin: 0 0 8px 0; color: #0f172a; font-size: 36px; font-weight: 900;}
          .header p { margin: 0; color: #64748b; font-size: 18px; font-weight: 600;}
          .rank-badge { background: #ffc800; color: #a16300; padding: 8px 20px; border-radius: 9999px; font-size: 18px; font-weight: 900; display: inline-block; margin-top: 10px; border-bottom: 4px solid #e5b400;}
          .stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 40px; }
          .stat-card { background: #ffffff; padding: 20px; border-radius: 24px; border: 2px solid #e2e8f0; border-bottom: 6px solid #e2e8f0; text-align: center; }
          .stat-card .label { font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; margin-bottom: 8px; font-weight: 800; }
          .stat-card .value { font-size: 28px; font-weight: 900; color: #0f172a; }
          .stat-card .value.xp { color: #ffc800; }
          table { width: 100%; border-collapse: separate; border-spacing: 0 12px; margin-bottom: 40px; }
          th, td { padding: 20px; text-align: left; }
          th { background: transparent; font-weight: 800; color: #94a3b8; text-transform: uppercase; font-size: 14px; letter-spacing: 0.05em; border-bottom: 2px solid #e2e8f0;}
          tr.row { background: #ffffff; }
          tr.row td { border-top: 2px solid #e2e8f0; border-bottom: 6px solid #e2e8f0; }
          tr.row td:first-child { border-left: 2px solid #e2e8f0; border-radius: 20px 0 0 20px; font-weight: 800;}
          tr.row td:last-child { border-right: 2px solid #e2e8f0; border-radius: 0 20px 20px 0; font-weight: 900; color: #ffc800;}
          .q-block { margin-bottom: 32px; background: #f8fafc; padding: 24px; border-radius: 24px; border: 2px solid #e2e8f0; }
          .q-type { font-weight: 900; color: #1cb0f6; margin-bottom: 12px; font-size: 20px; display: flex; justify-content: space-between; align-items: center;}
          .q-score { font-size: 16px; color: #ffc800; background: #fff4cc; padding: 6px 16px; border-radius: 99px;}
          .q-text { font-size: 18px; line-height: 1.6; color: #334155; font-weight: 600; }
          .footer { text-align: center; margin-top: 60px; padding-top: 32px; color: #cbd5e1; font-size: 16px; font-weight: 700; }
        </style>
      </head>
      <body onload="window.print()">
        <div class="header">
          <img src="${MASCOT_IMG}" alt="Bloomer Mascot" />
          <div>
            <h1>Article Mastery Complete</h1>
            <p>${dateStr} • ${uploadedArticle.name}</p>
            <div class="rank-badge">${rankName}</div>
          </div>
        </div>
        
        <div class="stats-grid">
          <div class="stat-card">
            <div class="label">Total XP</div>
            <div class="value xp">${totalXP}</div>
          </div>
          <div class="stat-card">
            <div class="label">Total Time</div>
            <div class="value">${formatTime(totalTimeInSecs)}</div>
          </div>
          <div class="stat-card">
            <div class="label">Mastery</div>
            <div class="value" style="color: #58cc02;">3/3</div>
          </div>
          <div class="stat-card">
            <div class="label">Attempts</div>
            <div class="value">${attemptHistory[1].length + attemptHistory[2].length + attemptHistory[3].length}</div>
          </div>
        </div>

        <table>
          <thead>
            <tr>
              <th>Question Type</th>
              <th>Attempts</th>
              <th>Time Spent</th>
              <th>Bloom's Level</th>
              <th>Points Earned</th>
            </tr>
          </thead>
          <tbody>
            ${QUESTIONS.map(q => `
              <tr class="row">
                <td>${q.title}</td>
                <td>${attemptHistory[q.id].length}</td>
                <td>${formatTime(questionTimes[q.id])}</td>
                <td style="color: #58cc02; font-weight: 800;">Level ${feedbacks[q.id]?.bloomLevel || 3}</td>
                <td>+${getXP(feedbacks[q.id]?.bloomLevel)} XP</td>
              </tr>
            `).join('')}
          </tbody>
        </table>

        <h2 style="font-weight: 900; color: #0f172a; margin-bottom: 24px;">Final Questions</h2>
        ${QUESTIONS.map(q => `
          <div class="q-block">
            <div class="q-type">
                ${q.title}
                <span class="q-score">Level ${feedbacks[q.id]?.bloomLevel || 3} Score</span>
            </div>
            <div class="q-text">"${inputs[q.id]}"</div>
          </div>
        `).join('')}

        <div class="footer">
          Generated by Bloomer • The Epilepsy + Data Science Lab • Harvard BIDMC
        </div>
      </body>
      </html>
    `;
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');
  };

  // --- RENDERERS ---

  if (appState === 'landing') {
    return (
      <div className="min-h-screen bg-[#ffffff] flex flex-col overflow-hidden font-sans text-[#4b4b4b]">
        <main className="flex-1 flex items-center justify-center p-6 sm:p-10">
          <div className="max-w-6xl w-full grid md:grid-cols-2 gap-12 sm:gap-20 items-start">
            
            <div className="space-y-8 mt-10">
              <div className="bg-[#e0f2fe] w-36 h-36 rounded-full border-4 border-[#bae6fd] shadow-sm flex items-center justify-center overflow-hidden">
                <img src={MASCOT_IMG} alt="Bloomer Mascot" className="w-full h-full object-cover translate-y-2" />
              </div>
              <div>
                <h1 className="text-5xl font-black text-[#1cb0f6] tracking-tight mb-4">bloomer</h1>
                <p className="text-xl font-medium text-[#777777] leading-relaxed max-w-lg">
                  Upload a research article. Write questions. Level up your understanding and climb the leaderboard.
                </p>
              </div>

              <button
                onClick={() => setAppState('upload')}
                className="bg-[#58cc02] hover:bg-[#46a302] active:translate-y-1 active:border-b-0 text-white px-10 py-4 rounded-2xl font-bold text-xl border-b-4 border-[#58a700] transition-all flex items-center gap-2 w-fit uppercase tracking-wider"
              >
                Get Started
              </button>
            </div>

            <div className="bg-white p-8 rounded-3xl border-2 border-[#e5e5e5] border-b-8 pointer-events-none select-none">
              <div className="flex items-center justify-between mb-8">
                <h3 className="text-lg font-black text-[#afafaf] uppercase tracking-widest">Bloom's XP</h3>
                <span className="text-sm bg-[#d7ffb8] text-[#58a700] px-3 py-1.5 rounded-xl font-bold border-2 border-[#58cc02]">Pass = Lvl 3+</span>
              </div>
              <div className="space-y-5">
                {bloomLevels.map((level) => (
                  <div key={level.level} className={`flex items-center justify-between ${level.level < 3 ? 'opacity-40 grayscale' : ''}`}>
                    <div className="flex items-center gap-4">
                        <span className={`text-3xl font-black ${level.color} w-8`}>{level.level}</span>
                        <div>
                        <div className="font-bold text-[#4b4b4b] text-lg">{level.name}</div>
                        <div className="text-sm font-medium text-[#afafaf]">{level.description}</div>
                        </div>
                    </div>
                    {level.level >= 3 && (
                        <div className="font-black text-lg text-[#ffc800] flex items-center gap-1">
                            <Flame className="w-5 h-5"/> +{getXP(level.level)}
                        </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

          </div>
        </main>
        
        <footer className="bg-white border-t-2 border-[#e5e5e5] py-6 text-center font-bold text-sm text-[#afafaf]">
          <p className="mb-1">
            <a href="#" className="hover:text-[#1cb0f6] transition-colors">The Epilepsy + Data Science Lab</a>
          </p>
          <p>Harvard BIDMC, Division of Epilepsy • Relentless incremental improvement</p>
        </footer>
      </div>
    );
  }

  if (appState === 'upload') {
    return (
      <div className="min-h-screen bg-[#ffffff] flex flex-col font-sans">
        <header className="bg-white border-b-2 border-[#e5e5e5] px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src={MASCOT_IMG} alt="Mascot" className="w-10 h-10 rounded-full bg-[#e0f2fe]" />
            <h1 className="font-black text-2xl text-[#1cb0f6]">bloomer</h1>
          </div>
          <button onClick={() => setAppState('landing')} className="text-[#afafaf] hover:text-[#4b4b4b] font-bold uppercase tracking-wider text-sm">
            Exit
          </button>
        </header>

        <main className="flex-1 flex flex-col items-center justify-center p-8 max-w-3xl mx-auto w-full">
          {!uploadedArticle ? (
            <div className="w-full relative group">
              <input 
                type="file" 
                accept=".pdf" 
                onChange={handleFileUpload} 
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
              />
              <div className="border-4 border-dashed border-[#e5e5e5] rounded-3xl bg-white p-16 text-center group-hover:border-[#1cb0f6] group-hover:bg-[#f0f9ff] transition-all duration-300">
                <div className="bg-[#1cb0f6] w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-6 shadow-sm">
                  <Upload className="w-12 h-12 text-white" />
                </div>
                <h2 className="text-3xl font-black text-[#4b4b4b] mb-2">Upload Article</h2>
                <p className="font-bold text-[#afafaf] mb-6">Drag and drop your PDF here</p>
              </div>
            </div>
          ) : (
            <div className="w-full bg-white rounded-3xl border-2 border-[#e5e5e5] border-b-8 p-10 text-center animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div className="bg-[#58cc02] w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-6 shadow-sm">
                <FileText className="w-12 h-12 text-white" />
              </div>
              <h2 className="text-2xl font-black text-[#4b4b4b] mb-2 truncate max-w-xl mx-auto" title={uploadedArticle.name}>
                {uploadedArticle.name}
              </h2>
              <p className="font-bold text-[#afafaf] mb-10">{uploadedArticle.size} • Ready for analysis</p>
              
              <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
                <button 
                  onClick={() => setUploadedArticle(null)}
                  className="w-full sm:w-auto px-8 py-4 bg-white text-[#afafaf] font-bold uppercase tracking-wider border-2 border-[#e5e5e5] border-b-4 hover:bg-gray-50 rounded-2xl active:border-b-2 active:translate-y-0.5 transition-all"
                >
                  Change File
                </button>
                <button 
                  onClick={() => setAppState('questions')}
                  className="w-full sm:w-auto px-10 py-4 bg-[#1cb0f6] hover:bg-[#1899d6] text-white font-bold uppercase tracking-wider rounded-2xl border-b-4 border-[#1899d6] active:border-b-0 active:translate-y-1 transition-all"
                >
                  Continue
                </button>
              </div>
            </div>
          )}
        </main>
      </div>
    );
  }

  if (appState === 'questions') {
    const progressPercent = (passedCount / 3) * 100;

    return (
      <div className="min-h-screen bg-[#ffffff] flex flex-col font-sans pb-40">
        {/* DUOLINGO BOTTOM DRAWER */}
        {drawerData && (
          <div className={`fixed bottom-0 left-0 w-full p-4 sm:p-8 border-t-[3px] z-[100] flex justify-center animate-in slide-in-from-bottom-8 duration-300 ${
            drawerData.status === 'PASS' ? 'bg-[#d7ffb8] border-[#58cc02]' : 'bg-[#ffdfe0] border-[#ea2b2b]'
          }`}>
            <div className="max-w-4xl w-full flex flex-col sm:flex-row items-center justify-between gap-6">
              <div className="flex items-center gap-6 w-full sm:w-auto">
                <div className={`w-20 h-20 rounded-full flex items-center justify-center shrink-0 hidden sm:flex bg-white ${drawerData.status === 'PASS' ? 'text-[#58cc02]' : 'text-[#ea2b2b]'}`}>
                  {drawerData.status === 'PASS' ? <CheckCircle2 size={48} strokeWidth={3} /> : <XCircle size={48} strokeWidth={3} />}
                </div>
                <div>
                  <h2 className={`text-3xl font-black mb-2 ${drawerData.status === 'PASS' ? 'text-[#58a700]' : 'text-[#ea2b2b]'}`}>
                    {drawerData.status === 'PASS' ? 'Excellent!' : 'Not quite right.'}
                  </h2>
                  <p className={`font-bold text-lg mb-2 ${drawerData.status === 'PASS' ? 'text-[#46a302]' : 'text-[#cb2222]'}`}>
                     {drawerData.feedback}
                  </p>
                  <div className="flex items-center gap-3 font-bold">
                     <span className={`px-3 py-1 rounded-xl text-sm uppercase tracking-wider ${drawerData.status === 'PASS' ? 'bg-[#58cc02] text-white' : 'bg-[#ea2b2b] text-white'}`}>
                        Level {drawerData.bloomLevel}: {drawerData.detectedLevel}
                     </span>
                     {drawerData.status === 'PASS' && (
                         <span className="text-[#ffc800] font-black flex items-center gap-1 drop-shadow-sm">
                             <Flame className="w-5 h-5"/> +{getXP(drawerData.bloomLevel)} XP
                         </span>
                     )}
                  </div>
                </div>
              </div>
              <button
                onClick={handleCloseDrawer}
                className={`w-full sm:w-auto px-10 py-4 rounded-2xl font-black uppercase tracking-widest text-white text-lg border-b-4 active:border-b-0 active:translate-y-1 transition-all whitespace-nowrap ${
                  drawerData.status === 'PASS' ? 'bg-[#58cc02] border-[#58a700] hover:bg-[#46a302]' : 'bg-[#ea2b2b] border-[#cb2222] hover:bg-[#d02424]'
                }`}
              >
                {drawerData.status === 'PASS' ? 'Continue' : 'Got It'}
              </button>
            </div>
          </div>
        )}

        {/* PROGRESS HEADER */}
        <header className="bg-white pt-6 pb-4 px-6 flex flex-col items-center sticky top-0 z-50">
           <div className="w-full max-w-4xl flex items-center justify-between gap-4 mb-2">
               <button onClick={() => setAppState('landing')} className="text-[#afafaf] hover:text-[#4b4b4b] transition-colors p-2">
                  <XCircle className="w-8 h-8" strokeWidth={2.5}/>
               </button>
               
               {/* Chunky Progress Bar */}
               <div className="flex-1 h-5 bg-[#e5e5e5] rounded-full overflow-hidden mx-2 relative">
                  <div 
                     className="h-full bg-[#58cc02] transition-all duration-700 ease-out rounded-full relative" 
                     style={{ width: `${progressPercent}%` }}
                  >
                      {/* Glossy highlight inside the bar */}
                      <div className="absolute top-1 left-2 right-2 h-1.5 bg-white/30 rounded-full"></div>
                  </div>
               </div>

               <div className="flex items-center gap-1.5 text-[#ffc800] font-black text-xl">
                  <Flame className="w-8 h-8 fill-current" />
                  {totalXP}
               </div>
           </div>
        </header>

        <main className="flex-1 max-w-3xl w-full mx-auto p-4 sm:p-6 space-y-10">
          {QUESTIONS.map((q) => {
            const isUnlocked = currentQuestionId >= q.id;
            const feedback = feedbacks[q.id];
            const isPassed = feedback?.status === 'PASS';
            const isEvaluating = evaluating.has(q.id);

            if (!isUnlocked) return null;

            return (
              <div key={q.id} className="animate-in fade-in slide-in-from-bottom-8 duration-500">
                <div className="flex items-end gap-4 mb-4">
                  <div className="bg-white border-2 border-[#e5e5e5] rounded-3xl p-5 shadow-sm relative w-full">
                     <h2 className="font-black text-xl text-[#4b4b4b] mb-1">{q.title}</h2>
                     <p className="font-bold text-[#afafaf] text-sm">{q.objective}</p>
                     
                     {/* Tip Toggle */}
                     <button 
                        onClick={() => toggleGuidance(q.id)}
                        className="mt-3 flex items-center gap-1.5 text-[#1cb0f6] font-bold text-sm hover:opacity-80 transition-opacity"
                     >
                        <Lightbulb className="w-5 h-5" />
                        {collapsedGuidance.has(q.id) ? "Show Hints" : "Hide Hints"}
                     </button>

                     {/* The Hints Box */}
                     {!collapsedGuidance.has(q.id) && (
                         <div className="mt-4 bg-[#f0f9ff] border-2 border-[#bae6fd] rounded-2xl p-4 text-sm font-medium text-[#4b4b4b] space-y-4">
                            <div>
                                <strong className="text-[#1cb0f6] uppercase tracking-wider text-xs block mb-1">What to do:</strong>
                                {q.guidance.lookingFor}
                            </div>
                            <div className="grid sm:grid-cols-2 gap-4">
                                <div>
                                    <strong className="text-[#58cc02] uppercase tracking-wider text-xs block mb-1">Do this:</strong>
                                    <ul className="space-y-1">
                                      {q.guidance.criteria.map((c, i) => <li key={i} className="flex gap-2"><CheckCircle2 className="w-4 h-4 text-[#58cc02] shrink-0"/>{c}</li>)}
                                    </ul>
                                </div>
                                <div>
                                    <strong className="text-[#ea2b2b] uppercase tracking-wider text-xs block mb-1">Don't do this:</strong>
                                    <ul className="space-y-1">
                                      {q.guidance.failures.map((f, i) => <li key={i} className="flex gap-2"><XCircle className="w-4 h-4 text-[#ea2b2b] shrink-0"/>{f}</li>)}
                                    </ul>
                                </div>
                            </div>
                         </div>
                     )}
                  </div>
                </div>

                {/* Question Input Area */}
                <div>
                  <textarea
                    value={inputs[q.id]}
                    onChange={(e) => setInputs(prev => ({ ...prev, [q.id]: e.target.value }))}
                    placeholder="Type your question here..."
                    className={`w-full h-40 p-5 font-medium text-lg border-2 rounded-2xl outline-none resize-none transition-all ${
                        isPassed 
                          ? 'bg-[#f7f7f7] border-[#e5e5e5] text-[#afafaf] cursor-default' 
                          : 'bg-[#f7f7f7] border-[#e5e5e5] focus:bg-white focus:border-[#1cb0f6] text-[#4b4b4b]'
                    }`}
                    disabled={isEvaluating || isPassed}
                  />

                  {/* detailed suggestions visible ONLY after passing and continuing */}
                  {isPassed && feedback.suggestions && (
                      <div className="mt-4 bg-white border-2 border-[#e5e5e5] rounded-2xl p-5">
                          <h4 className="font-black text-[#afafaf] uppercase tracking-wider text-sm mb-3">Your Understanding Breakdown</h4>
                          <ul className="space-y-2 font-bold text-[#4b4b4b]">
                              {feedback.suggestions.map((s, i) => (
                                  <li key={i} className="flex items-start gap-3">
                                      <div className="w-2 h-2 rounded-full bg-[#1cb0f6] mt-2 shrink-0"></div>
                                      {s}
                                  </li>
                              ))}
                          </ul>
                          {feedback.bloomLevel < 6 && q.id === currentQuestionId && (
                              <button
                                onClick={() => resetQuestion(q.id)}
                                className="mt-5 w-full py-3 border-2 border-[#e5e5e5] text-[#afafaf] font-bold uppercase tracking-wider rounded-xl hover:bg-gray-50 active:translate-y-0.5 transition-all"
                              >
                                Edit to try for a higher score
                              </button>
                          )}
                      </div>
                  )}

                  {!isPassed && (
                      <button
                        onClick={() => handleEvaluate(q.id)}
                        disabled={!inputs[q.id].trim() || isEvaluating}
                        className="mt-4 w-full bg-[#58cc02] hover:bg-[#46a302] disabled:bg-[#e5e5e5] disabled:border-[#e5e5e5] disabled:text-[#afafaf] disabled:transform-none disabled:cursor-not-allowed text-white py-4 rounded-2xl font-black text-lg uppercase tracking-wider border-b-4 border-[#58a700] active:border-b-0 active:translate-y-1 transition-all flex items-center justify-center gap-2"
                      >
                        {isEvaluating ? <><Loader2 className="w-6 h-6 animate-spin" /> Checking...</> : "Check Answer"}
                      </button>
                  )}
                </div>
              </div>
            );
          })}
        </main>
      </div>
    );
  }

  if (appState === 'mastery') {
    const totalTime = Object.values(questionTimes).reduce((a, b) => a + b, 0);
    const avgAttempts = (Object.values(attemptHistory).reduce((sum, arr) => sum + arr.length, 0) / 3).toFixed(1);
    const rankName = getRank(totalXP);

    return (
      <div className="min-h-screen bg-[#ffffff] flex items-center justify-center p-4 sm:p-8 font-sans">
        <div className="max-w-3xl w-full bg-white rounded-3xl border-2 border-[#e5e5e5] border-b-8 p-6 sm:p-12 animate-in zoom-in-95 duration-500">
          
          <div className="text-center">
            <img src={MASCOT_IMG} alt="Mascot" className="w-32 h-32 rounded-full mx-auto mb-6 border-4 border-[#e0f2fe] bg-[#e0f2fe] animate-bounce" style={{animationDuration: '2s'}}/>
            
            <div className="inline-flex items-center gap-2 px-6 py-2 rounded-full bg-[#ffc800] text-white text-lg font-black uppercase tracking-widest mb-6 border-b-4 border-[#e5b400]">
              <Trophy className="w-5 h-5 fill-current" /> {rankName}
            </div>
            
            <h1 className="text-4xl font-black text-[#4b4b4b] mb-4">Lesson Complete!</h1>
            
            <div className="bg-[#f0f9ff] text-[#1cb0f6] font-bold px-6 py-3 rounded-2xl inline-block border-2 border-[#bae6fd] mb-10 max-w-full truncate">
              {uploadedArticle?.name}
            </div>

            <div className="grid grid-cols-2 gap-4 mb-8">
              <div className="bg-white border-2 border-[#e5e5e5] rounded-2xl p-4 flex flex-col items-center justify-center">
                <div className="text-sm font-black text-[#afafaf] uppercase tracking-wider mb-1">Total XP</div>
                <div className="text-3xl font-black text-[#ffc800] flex items-center gap-1">
                    <Flame className="w-6 h-6 fill-current"/> {totalXP}
                </div>
              </div>
              <div className="bg-white border-2 border-[#e5e5e5] rounded-2xl p-4 flex flex-col items-center justify-center">
                <div className="text-sm font-black text-[#afafaf] uppercase tracking-wider mb-1">Time</div>
                <div className="text-3xl font-black text-[#1cb0f6]">{formatTime(totalTime)}</div>
              </div>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row gap-4 mt-8">
            <button
              onClick={generateCertificate}
              className="w-full sm:w-1/2 py-4 bg-white border-2 border-[#e5e5e5] border-b-4 hover:bg-gray-50 text-[#afafaf] rounded-2xl font-black uppercase tracking-wider text-lg active:border-b-2 active:translate-y-0.5 transition-all flex items-center justify-center gap-2"
            >
              <Download className="w-6 h-6" /> Save PDF
            </button>
            <button
              onClick={() => {
                setAppState('landing');
                setUploadedArticle(null);
                setInputs({ 1: '', 2: '', 3: '' });
                setFeedbacks({});
                setAttemptHistory({ 1: [], 2: [], 3: [] });
                setCurrentQuestionId(1);
                setQuestionTimes({ 1: 0, 2: 0, 3: 0 });
                setCollapsedGuidance(new Set([2, 3]));
              }}
              className="w-full sm:w-1/2 py-4 bg-[#1cb0f6] hover:bg-[#1899d6] text-white rounded-2xl font-black uppercase tracking-wider text-lg border-b-4 border-[#1899d6] active:border-b-0 active:translate-y-1 transition-all"
            >
              Finish
            </button>
          </div>
          
        </div>
      </div>
    );
  }

  return null;
}