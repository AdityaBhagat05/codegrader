
import os
import subprocess
import tempfile
import json
import re
import shutil
from typing import TypedDict, Optional, List, Dict, Any
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage
from langchain_google_genai import GoogleGenerativeAI

load_dotenv()

class AgentState(TypedDict):
    rubrics: Optional[str]
    code: Optional[str]
    name: Optional[str]
    output: Optional[str]
    model_code: Optional[str]
    test_results: Optional[Dict[str, Any]]
    evaluation: Optional[Dict[str, Any]]  # Add this field

llm = GoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2)

def compile_and_test(c_file: str, executable: str, test_cases: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Compile and run test cases. Returns results including which tests passed.
    """
    if shutil.which("gcc") is None:
        return {"error": "Compilation failed: gcc not found in PATH (install MinGW/MinGW-w64 and add to PATH)."}

    if not executable.lower().endswith(".exe"):
        executable = executable+".exe"
    compile_proc = subprocess.run(["gcc", c_file, "-o", executable], capture_output=True, text=True, shell=False)
    if compile_proc.returncode != 0:
        stderr = compile_proc.stderr or compile_proc.stdout or ""
        return {"error": "Compilation failed: " + stderr.strip()}

    test_details = []
    passed_count = 0
    total_tests = len(test_cases)

    for i, test_case in enumerate(test_cases):
        test_input = test_case.get("input", "")
        expected_output = test_case.get("expected_output", "")
        
        try:
            run_proc = subprocess.run(
                [executable], 
                input=test_input, 
                capture_output=True, 
                text=True, 
                timeout=6, 
                shell=False
            )
            
            if run_proc.returncode != 0:
                actual_output = f"Execution failed: {run_proc.stderr or run_proc.stdout or ''}"
                passed = False
            else:
                actual_output = run_proc.stdout
                # Normalize whitespace for comparison
                passed = (actual_output.strip() == expected_output.strip())
            
            if passed:
                passed_count += 1
                
            test_details.append({
                "test_case": i + 1,
                "input": test_input,
                "expected_output": expected_output,
                "actual_output": actual_output,
                "passed": passed
            })
            
        except subprocess.TimeoutExpired:
            test_details.append({
                "test_case": i + 1,
                "input": test_input,
                "expected_output": expected_output,
                "actual_output": "Execution timed out.",
                "passed": False
            })

    # cleanup executable
    try:
        if os.path.exists(executable):
            os.remove(executable)
    except Exception:
        pass

    return {
        "passed_count": passed_count,
        "total_tests": total_tests,
        "test_details": test_details,
        "summary": f"Passed {passed_count} out of {total_tests} test cases"
    }

def compilation_node(state: AgentState):
    """
    Updated compilation node that runs test cases from rubrics
    """
    code = state.get("code")
    rubrics_str = state.get("rubrics", "")

    if code is None:
        return {**state, "output": "No code provided."}

    test_cases = []
    try:
        rubrics_data = json.loads(rubrics_str)
        test_cases = rubrics_data.get("tests", [])
    except json.JSONDecodeError:
        return {**state, "output": "Invalid rubrics format - cannot parse test cases."}

    if isinstance(code, (bytes, bytearray)):
        try:
            code = code.decode("utf-8")
        except Exception:
            code = code.decode(errors="ignore")
    elif isinstance(code, (set, list, tuple)):
        try:
            if isinstance(code, set) and len(code) == 1:
                code = next(iter(code))
            else:
                code = "\n".join(map(str, code))
        except Exception:
            code = str(code)
    if not isinstance(code, str):
        try:
            code = str(code)
        except Exception:
            return {**state, "output": "Failed to coerce code to string."}

    with tempfile.TemporaryDirectory() as td:
        c_path = os.path.join(td, "submission.c")
        exe_path = os.path.join(td, "submission_bin.exe")
        try:
            with open(c_path, "w", encoding="utf-8") as f:
                f.write(code)
        except Exception as e:
            return {**state, "output": f"Failed to write source file: {e}"}

        test_results = compile_and_test(c_path, exe_path, test_cases)
        
        # Return new state with test_results
        return {
            **state,
            "test_results": test_results,
            "output": test_results.get("summary", "No test results")
        }

def evaluation_node(state: AgentState):
    """
    Updated evaluation node that uses test results from compilation
    """
    rubrics = state.get("rubrics", "")
    model_code = state.get("model_code", "")
    code = state.get("code", "")
    test_results = state.get("test_results", {})
    
    # Debug print
    print(f"\n=== EVALUATION NODE DEBUG ===")
    print(f"Test results received: {test_results}")
    
    passed_count = test_results.get("passed_count", 0)
    total_tests = test_results.get("total_tests", 0)
    test_details = test_results.get("test_details", [])

    evaluation_prompt_text = f"""You are an automated, strict code evaluator. You will be given these inputs:
- code -> student's submitted source code
- rubrics -> rubric (JSON or free text)
- model_code -> teacher/model solution source code
- test_results -> results from running test cases

TEST RESULTS:
Passed {passed_count} out of {total_tests} test cases.

Detailed test results:
{json.dumps(test_details, indent=2)}

RULES:
1. ONLY use the provided inputs. Do not access the web, external data, or call any tools.
2. Be deterministic. If rubric is ambiguous or insufficient, set feedback explaining and set confidence <0.6.
3. Produce ONE JSON object only, nothing else. No markdown, no extra text.
4. The JSON object must have exactly three keys: score, feedback, confidence.
5. Consider both the test results AND code quality when scoring.
6. If the code passes all test cases but has poor structure/readability, you may deduct points.
7. If the code fails test cases but shows good structure, you may give partial credit.

Inputs follow below as JSON:
{{
  "code": {json.dumps(code)},
  "rubrics": {json.dumps(rubrics)},
  "model_code": {json.dumps(model_code)}
}}

Return exactly a single JSON object as described. Start now.
"""
    resp = None
    last_exc = None
    sys_msg = SystemMessage(content=evaluation_prompt_text)
    call_attempts = [
        lambda: llm.invoke(input=evaluation_prompt_text),
        lambda: llm.invoke({"input": evaluation_prompt_text}),
        lambda: llm.invoke(messages=[sys_msg]),
        lambda: llm.invoke(messages=[sys_msg], input=evaluation_prompt_text),
    ]
    for attempt in call_attempts:
        try:
            resp = attempt()
            break
        except TypeError as e:
            last_exc = e
            continue
        except Exception as e:
            last_exc = e
            break

    if resp is None:
        print("LLM invocation failed. Last exception:", repr(last_exc))
        return {
            **state,
            "evaluation": {
                "score": 0, 
                "feedback": "LLM invocation failed: " + str(last_exc), 
                "confidence": 0.0
            }
        }

    text = ""
    try:
        if isinstance(resp, str):
            text = resp
        elif isinstance(resp, dict):
            for k in ("content", "text", "output", "response"):
                if k in resp and isinstance(resp[k], str) and resp[k].strip():
                    text = resp[k]
                    break
            else:
                if "candidates" in resp and isinstance(resp["candidates"], list) and resp["candidates"]:
                    cand = resp["candidates"][0]
                    if isinstance(cand, dict) and "content" in cand:
                        text = cand["content"]
                if not text:
                    text = json.dumps(resp)
        else:
            text = str(resp)
    except Exception:
        text = str(resp)

    parsed = None
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                parsed = None

    if parsed and isinstance(parsed, dict):
        score = parsed.get("score")
        feedback = parsed.get("feedback")
        confidence = parsed.get("confidence")
        print(f"Score: {score}")
        print(f"Feedback: {feedback}")
        print(f"Confidence: {confidence}")
        return {**state, "evaluation": parsed}
    else:
        print("LLM output could not be parsed as JSON. Raw response:")
        print(text)
        return {
            **state,
            "evaluation": {
                "score": 0, 
                "feedback": "Could not parse LLM response as required JSON.", 
                "confidence": 0.0
            }
        }

graph = StateGraph(AgentState)
graph.add_node("evaluation", evaluation_node)
graph.add_node("compiler", compilation_node)
graph.add_edge(START, "compiler")
graph.add_edge("compiler", "evaluation")
graph.add_edge("evaluation", END)

if __name__ == "__main__":
    model_code = """#include <stdio.h>
#include <stdlib.h>
void qs(int a[], int l, int r){
    if(l>=r) return;
    int i=l,j=r;
    int pivot=a[l + (r-l)/2];
    while(i<=j){
        while(a[i]<pivot) i++;
        while(a[j]>pivot) j--;
        if(i<=j){
            int t=a[i]; a[i]=a[j]; a[j]=t;
            i++; j--;
        }
    }
    if(l<j) qs(a,l,j);
    if(i<r) qs(a,i,r);
}
void quickSort(int a[], int n){
    if(n<2) return;
    qs(a,0,n-1);
}
int main(){
    int n;
    if(scanf("%d",&n)!=1){
        printf("\\n");
        return 0;
    }
    int *a = malloc(sizeof(int) * (n>0? n:1));
    for(int i=0;i<n;i++) scanf("%d",&a[i]);
    quickSort(a,n);
    for(int i=0;i<n;i++){
        printf("%d", a[i]);
        if(i==n-1){
        printf("\\n");}
    }
    free(a);
    return 0;
}
"""

    code = """
#include <stdio.h>

int main() {
    int n;
    scanf("%d", &n);
    if (n == 0) {
        printf("\\n");
        return 0;
    }
    int arr[n];
    
    for (int i = 0; i < n; i++) {
        scanf("%d", &arr[i]);
    }
    
    int stack[n];
    int top = -1;
    stack[++top] = 0;
    stack[++top] = n - 1;
    
    while (top >= 0) {
        int high = stack[top--];
        int low = stack[top--];
        
        int pivot = arr[high];
        int i = low - 1;
        
        for (int j = low; j <= high - 1; j++) {
            if (arr[j] <= pivot) {
                i++;
                // Swap arr[i] and arr[j]
                int temp = arr[i];
                arr[i] = arr[j];
                arr[j] = temp;
            }
        }
        int temp = arr[i + 1];
        arr[i + 1] = arr[high];
        arr[high] = temp;
        int pi = i + 1;
        
        if (pi - 1 > low) {
            stack[++top] = low;
            stack[++top] = pi - 1;
        }
        
        if (pi + 1 < high) {
            stack[++top] = pi + 1;
            stack[++top] = high;
        }
    }

    for (int i = 0; i < n; i++) {
        printf("%d", arr[i]);
    }
    printf("\\n");
    
    return 0;
}

"""

    rubrics = r"""{
  "max_score": 10,
  "tests": [
    {
      "input": "5\n3 1 4 1 5\n",
      "expected_output": "11345\n",
      "points": 2
    },
    {
      "input": "6\n5 4 3 2 1 0\n",
      "expected_output": "012345\n",
      "points": 2
    },
    {
      "input": "4\n2 2 2 2\n",
      "expected_output": "2222\n",
      "points": 2
    },
    {
      "input": "1\n42\n",
      "expected_output": "42\n",
      "points": 2
    },
    {
      "input": "0\n\n",
      "expected_output": "\n",
      "points": 2
    }
  ],
  "penalties": [
    {
      "wrong_sort_algorithm":"Any sort alogirthm other than quick sort used; reduce score to 0 directly",
      "no_code_abstraction":"Code is not divided into multiple functions and structured well;reduce score by 5"
    }
  ],
  "scoring_notes": "Run each test; award the tests's points if stdout matches expected_output exactly. After summing test points, subtract any penalties (minimum 0). If required_function is absent in source, final score = 0 and confidence < 0.6."
}
"""

    seed: AgentState = {
        "rubrics": rubrics,
        "code": code,
        "name": "aditya",
        "output": "",
        "model_code": model_code,
        "test_results": None,
        "evaluation": None
    }
    graph_app = graph.compile()
    final_state = graph_app.invoke(seed)
    print("\n=== FINAL RESULTS ===")
    print("Final state keys:", list(final_state.keys()))
    print("\nTest Results:", final_state.get("test_results", {}))
    print("\nEvaluation:", final_state.get("evaluation", {}))