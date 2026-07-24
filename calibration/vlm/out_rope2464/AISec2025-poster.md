# CyberLLMInstruct: A Pseudo-malicious Dataset Revealing Safety-performance Trade-offs in Cyber Security LLM Fine-tuning

Our research introduces CyberLLMInstruct, a dataset of 54,928 pseudo-malicious instruction-response pairs. We found that fine-tuning Large Language Models (LLMs) on this dataset dramatically improves cyber security task performance but severely compromises their safety resilience against attacks like prompt injection.

## Authors

- Adel ElZemity  
  AE455@kent.ac.uk  
  ORCID: 0000-0002-5402-7837

- Budi Arief  
  ORCID: 0000-0002-1830-1587

- Shujun Li  
  ORCID: 0000-0001-5628-7328

## Affiliation

University of Kent

---

## Introduction

- **Problem Statement**: LLMs are being integrated into cyber security for tasks like malware analysis and threat detection. However, fine-tuning them for these specific tasks may introduce critical safety vulnerabilities.

- **Research Gap**: There is a lack of comprehensive datasets and evaluations that expose the trade-off between task performance and safety resilience in LLMs fine-tuned for cyber security (see Table 1).

- **Objective**: To introduce the CyberLLMInstruct dataset and evaluate how fine-tuning impacts both the performance and safety of LLMs in a cyber security context (see Table 2).

---

## Methodology

### Figure 1: Security categories in CyberLLMInstruct dataset

![Pie chart showing security categories: Malware (19,224), Social Engineering (13,732), DoS/DDoS (5,493), MITM (5,493), Zero-Day (4,394), Password (3,296), IoT (1,648), Injection (1,648)]

### Figure 2: A high-level overview of the dataset creation process

![Flowchart showing dataset creation steps: Gather diverse sources → Assign domains → Manual review → Final dataset assembly → Preliminary filtering → Format into Q/A pairs → Security alignment → AI-assisted tuning → Security Practitioners → Inference API → Vulnerability detection, Incident response automation, Threat intelligence, Malware generation, Attack automation, Less experienced Malicious Actors]

### Figure 3: Abstraction of dual impacts of LLMs in cyber security

![Diagram showing interaction between Defense LLM, Security Researcher, Expert Adversary, Adversarial LLM, Open-source cyber security intelligence, Open-source large language models]

---

## Dataset Utility

### Table 1: Comparison of CyberLLMInstruct with other cyber security datasets

<table>
  <thead>
    <tr>
      <th>Dataset</th>
      <th>Scope</th>
      <th>Malicious Content</th>
      <th>Instruction Format</th>
      <th>Size</th>
      <th>Security Testing</th>
      <th>Primary Use</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>CyBERTuned [25]</td>
      <td>Large corpus for pretraining</td>
      <td>No</td>
      <td>No (text corpus)</td>
      <td>~700MB</td>
      <td>No direct vulnerability eval</td>
      <td>Pretraining LLMs for security awareness</td>
    </tr>
    <tr>
      <td>CySecBERT [4]</td>
      <td>Security news, CVE reports</td>
      <td>No</td>
      <td>No (text corpus)</td>
      <td>~4.3M documents</td>
      <td>Limited</td>
      <td>Domain-adaptive BERT for security tasks</td>
    </tr>
    <tr>
      <td>SecQA [26]</td>
      <td>Multiple-choice Q&amp;A</td>
      <td>No</td>
      <td>No (Q&amp;A pairs)</td>
      <td>127 Qs (v1)<br>115 Qs (v2)</td>
      <td>Not evaluated</td>
      <td>Basic security knowledge benchmarking</td>
    </tr>
    <tr>
      <td>CyberMetric [43]</td>
      <td>Large cyber security Q&amp;A benchmark</td>
      <td>No</td>
      <td>No (Q&amp;A format)</td>
      <td>10,000 questions</td>
      <td>Minimal</td>
      <td>Evaluating LLM knowledge in cybersecurity</td>
    </tr>
    <tr>
      <td>SVEN [19]</td>
      <td>Secure vs. insecure code pairs</td>
      <td>Insecure code snippets</td>
      <td>No (code diffs)</td>
      <td>803 fix pairs</td>
      <td>Some (prefix-tuning for safe vs. unsafe code)</td>
      <td>Code generation control (secure/insecure outputs)</td>
    </tr>
    <tr>
      <td>CyberLLMInstruct</td>
      <td>Instruction security cyber security dataset</td>
      <td>Yes (malicious + benign)</td>
      <td>Yes (full instruction format)</td>
      <td>54,928 records</td>
      <td>Yes, tested with OWASP framework</td>
      <td>Fine-tuning LLMs, adversarial testing, security training</td>
    </tr>
  </tbody>
</table>


*Note: All figure and table numbers in the poster match those in the paper.*

---

### Table 2: Accuracy results (%) for different base (before arrow) and fine-tuned (after arrow) LLMs on the CyberMetric benchmark

<table>
  <thead>
    <tr>
      <th>LLM Model</th>
      <th>80 Q</th>
      <th>500 Q</th>
      <th>2k Q</th>
      <th>10k Q</th>
      <th></th>
      <th></th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Phi 3 Mini 3.8B</td>
      <td>5.00 ± 0.0 → 53.75 ± 1.2</td>
      <td>5.00 ± 0.0 → 40.60 ± 1.0</td>
      <td>4.41 ± 0.0 → 28.75 ± 0.9</td>
      <td>4.80 ± 0.0 → 19.18 ± 0.7</td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>Mistral 7B</td>
      <td>78.75 ± 0.8 → 81.94 ± 1.0</td>
      <td>78.40 ± 0.9 → 91.80 ± 0.6</td>
      <td>76.40 ± 1.1 → 91.10 ± 0.7</td>
      <td>74.82 ± 1.0 → 88.89 ± 0.8</td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>Qwen 2.5 7B</td>
      <td>43.75 ± 1.1 → 73.75 ± 0.9</td>
      <td>58.00 ± 0.8 → 64.60 ± 1.0</td>
      <td>55.75 ± 1.0 → 69.00 ± 0.8</td>
      <td>54.09 ± 0.9 → 66.10 ± 0.7</td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>Llama 3 8B</td>
      <td>38.75 ± 0.9 → 82.50 ± 1.1</td>
      <td>35.80 ± 1.2 → 48.00 ± 0.9</td>
      <td>37.00 ± 1.0 → 49.45 ± 0.8</td>
      <td>36.00 ± 1.1 → 50.75 ± 1.0</td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>Llama 3.1 8B</td>
      <td>81.25 ± 0.7 → 92.50 ± 0.6</td>
      <td>76.20 ± 1.0 → 87.80 ± 0.9</td>
      <td>73.05 ± 0.9 → 91.25 ± 0.8</td>
      <td>71.25 ± 1.1 → 88.50 ± 0.7</td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>Gemma 2 9B</td>
      <td>42.50 ± 1.0 → 78.75 ± 0.8</td>
      <td>37.20 ± 0.9 → 52.80 ± 1.1</td>
      <td>36.00 ± 1.2 → 50.44 ± 0.9</td>
      <td>43.28 ± 1.0 → 59.79 ± 0.8</td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>Llama 2 70B</td>
      <td>75.00 ± 0.8 → 90.00 ± 0.7</td>
      <td>73.40 ± 0.9 → 78.40 ± 1.0</td>
      <td>71.60 ± 1.1 → 84.00 ± 0.8</td>
      <td>66.10 ± 1.0 → 74.82 ± 0.9</td>
      <td></td>
      <td></td>
    </tr>
  </tbody>
</table>


### Figure 4: Performance of base (green) and fine-tuned (red) LLMs against OWASP Top 10 vulnerabilities

<table>
  <thead>
    <tr>
      <th>Vulnerability</th>
      <th>Phi 3 Mini 3.8B</th>
      <th>Mistral 7B</th>
      <th>Qwen 2.5 7B</th>
      <th>Llama 3 8B</th>
      <th>Llama 3.1 8B</th>
      <th>Gemma 2 9B</th>
      <th>Llama 2 70B</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Prompt Injection</td>
      <td>0.80</td>
      <td>0.85</td>
      <td>0.81</td>
      <td>0.84</td>
      <td>0.80</td>
      <td>0.82</td>
      <td>0.82</td>
    </tr>
    <tr>
      <td>Sensitive Info. Disclosure</td>
      <td>0.89</td>
      <td>0.85</td>
      <td>0.84</td>
      <td>0.80</td>
      <td>0.78</td>
      <td>0.82</td>
      <td>0.82</td>
    </tr>
    <tr>
      <td>Supply Chain</td>
      <td>0.87</td>
      <td>0.82</td>
      <td>0.85</td>
      <td>0.86</td>
      <td>0.80</td>
      <td>0.83</td>
      <td>0.84</td>
    </tr>
    <tr>
      <td>Data and Model Poisoning</td>
      <td>0.85</td>
      <td>0.87</td>
      <td>0.89</td>
      <td>0.88</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
    </tr>
    <tr>
      <td>Improper Output Handling</td>
      <td>0.93</td>
      <td>0.86</td>
      <td>0.82</td>
      <td>0.82</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
    </tr>
    <tr>
      <td>Excessive Agency</td>
      <td>0.86</td>
      <td>0.85</td>
      <td>0.87</td>
      <td>0.84</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
    </tr>
    <tr>
      <td>Prompt Leakage</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.89</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
    </tr>
    <tr>
      <td>Embedding Weaknesses</td>
      <td>0.82</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
    </tr>
    <tr>
      <td>Misinformation</td>
      <td>0.93</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
    </tr>
    <tr>
      <td>Unbounded Consumption</td>
      <td>0.84</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
      <td>0.85</td>
    </tr>
  </tbody>
</table>


---

## Conclusion

- There is a clear, quantifiable trade-off between performance and safety.
  - Significant performance gains, with models achieving up to 92.50% accuracy on the CyberMetric benchmark (see Table 2).
  - Fine-tuning an LLM to be highly proficient in cyber security tasks consistently led to decreased security scores across all vulnerability categories. For example, Llama 3.1 8B’s security score dropped from 0.95 to 0.15 against prompt injection (see Figure 4).
  - Fine-tuning also reduced the inference efficiency for all models (see Figure 5).

- Model size and architecture affect safety resilience following fine-tuning using the CyberLLMInstruct dataset, with the effect varying across attack categories (see Figure 6).

- **Future Work**:
  - Develop new fine-tuning methodologies that can effectively balance performance gains with the preservation of safety and resilience.
  - Ablation analysis on different categories of cyber security data to understand how specific types of content, such as malware-related or social engineering data, affect model safety.

---

## Selected papers citing CyberLLMInstruct (as of 30 September 2025)

- Almorjan, A., Basheri, M., & Almasre, M. (2025). Large Language Models for Synthetic Dataset Generation of Cyber Security Indicators of Compromise. Sensors, 25(9), 2825. https://doi.org/10.3390/s25092825

- ElZemity, A., Arief, B., & Li, S. (2025). Analysing Safety Risks in LLMs Fine-Tuned With Pseudo-Malicious Cyber Security Data. Proceedings of the 2025 International Workshop on Security and Artificial Intelligence (SECAI 2025), 25–26 September 2025. arXiv preprint arXiv:2505.09974. https://doi.org/10.48550/arXiv.2505.09974

- Gungor, O., Sood, R., Wang, H., & Rosing, T. (2025). AQUA-LLM: Evaluating Accuracy, Quantization, and Adversarial Robustness Trade-Offs in LLMs for Cyber Security Question Answering. arXiv preprint arXiv:2509.13514. https://doi.org/10.48550/arXiv.2505.23397.

- Mohsin, A., Janicke, H., Ibrahim, A., Sarker, I. H., & Camtepe, S. (2025). A Unified Framework for Human–AI Collaboration in Security Operations Centers With Trusted Autonomy. arXiv preprint arXiv:2505.23397. https://doi.org/10.48550/arXiv.2505.23397

---

## CyberLLMInstruct GitHub Repository

github.com/adelsamir01/CyberLLMInstruct

## CyberLLMInstruct arXiv Preprint

arxiv.org/abs/2503.09334

![image](image_1.png)