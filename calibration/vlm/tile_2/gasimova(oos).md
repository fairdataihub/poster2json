# Clinical Dataset Structure: A Framework for Structuring Clinical Research

**Aydan Gasimova$^{1}$, Sanjay Soundarajan$^{1}$, Nayoon Gim$^{2,3,4}$, James**

$^{1}$FAIR Data Innovations Hub, California Medical Innovations Institute  
$^{2}$Department of Ophthalmology, University of California, San Francisco  
$^{3}$Department of Bioengineering, University of California, San Francisco  
$^{4}$The Roger and Angie Karalis Johnson Research Institute  
$^{5}$John F. Hardesty MD Department of Ophthalmology and Visual Rehabilitation

---

## Background

Each year, a rapidly growing volume of datasets is shared across the research community. In clinical studies, many data types are collected per participant, such as surveys, vital signs, eye images, and more. This data is expected to align with the **FAIR (Findable, Accessible, Interoperable, Reusable) Principles**.

## Problem

There is currently no consensus on how to organize multimodal data and include related information known as metadata. Standards like BIDS (Brain Imaging Data Structure) exist but only for structuring individual modalities. As a result, datasets from different studies are:

1. **Not interoperable.** The data cannot be directly combined with other datasets, workflows, and tools.
2. **Not reusable.** The data cannot be easily used by researchers other than the original creators.

---

### Figure 1. Illustration of the root level of a dataset


┌──────────────┐
│   cardiac_ecg │
├──────────────┤
│   retinal_oct │
├──────────────┤
│   README.md  │
├──────────────┤
│   LICENSE.txt │
├──────────────┤
│   healthsheet.md │
├──────────────┤
│   CHANGELOG.md │
├──────────────┤
│   study_description.json │
├──────────────┤
│   dataset_description.json │
├──────────────┤
│   datatype_dictionary.json │
├──────────────┤
│   participants.tsv │
├──────────────┤
│   participants.json │
└──────────────┘
```

---

![image](image_1.png)  
**CALIFORNIA MEDICAL INNOVATIONS INSTITUTE**

![image](image_2.png)  
**AI-READI**  
*AI Ready and Exploratory Areas for Diabetes Insights*

---

**? ? ?**

**Q**

**📄**

**Q**

**📄**

# Structure: A Universal Framework for Clinical Research Datasets

**Authors:**  
$^{2,3,4}$, Jamie Shaffer$^{5}$, Julia Owen$^{5}$, Aaron Lee$^{5}$, Bhavesh Patel$^{1}$

**Affiliations:**  
$^{2,3,4}$, Medical Innovations Institute, San Diego, CA, USA,  
$^{5}$, University of Washington, Seattle, WA, USA  
$^{1}$, University of Washington, Seattle, WA, USA  
$^{5}$, Johnson Retina Center, Seattle, WA, USA  
$^{1}$, Biology and Visual Sciences, Washington University, St. Louis, MO, USA

---

## Results

We established the Clinical Dataset Structure (CDS) a standard for organizing clinical research data and metadata.

The CDS provides several specifications:

- The CDS instructs to organize data into one folder per datatype at the root level (Fig. 1). It also prescribes a specific structure within each datatype folder (Fig 2).

- The CDS requires several metadata files to be included at the root-level that contain essential information for reusing the dataset (Fig. 1).

- Collectively, the metadata files capture **80+ metadata fields** including dataset description, study information, license terms, and more.

- The CDS also provides specification for naming the different folders and files consistently.

- The full specification is available at cds-specification.readthedocs.io.

- We are also developing pyfairdatatools, a Python package aimed at making it easier to implement the CDS.

---

### Folder Structure

- **Folders of the datatypes present in the dataset**

- **Metadata files containing information about the dataset in a human-friendly format**

- **Metadata files containing information about the dataset in a machine-friendly format**

---

*Level of a dataset structured following the CDS.*

---

**Logos:**

- FAIR DATA INNOVATIONS HUB  
  ![image](image_1.png)

- BRIDGE2AI  
  ![image](image_2.png)

---

*Note: The left column contains fragmented text that appears to be part of a table of authors or affiliations, but is cut off and incomplete in the image. It has been omitted for clarity and completeness.*

researchers other than the original creators.

<div style="display: flex; justify-content: space-between; align-items: center; margin: 20px 0;">
  <div style="text-align: center;">
    ![image](image_1.png)
    <p><strong>Original researchers</strong></p>
  </div>
  <div style="text-align: center;">
    ![image](image_2.png)
    <p><strong>Unorganized data and metadata</strong></p>
  </div>
  <div style="text-align: center;">
    ![image](image_3.png)
    <p><strong>New researchers</strong></p>
  </div>
</div>

## Purpose

The purpose of this work was to develop a standard for organizing clinical research data and associated metadata.

## Methods

1. Review and analyze existing standards for organizing specific datatypes (e.g. Brain Imaging Data Structure) and popular metadata schemas (e.g. DataCite and ClinicalTrials.gov)
2. Review and analyze AI/ML-specific data documentation practices (e.g. datasheet and healtsheet)
3. Combine review findings and our understanding of clinical research data for establishing the standard
4. Apply the standard to a real world dataset as a test case.

---

**Figure 1.** Illustration of the root level of a datas

<div style="display: flex; justify-content: space-between; align-items: center; margin: 20px 0;">
  <div style="text-align: center;">
    ![image](image_4.png)
    <p>datatype folder(s)</p>
  </div>
  <div style="text-align: center;">
    ![image](image_5.png)
    <p>modality folder(s)</p>
  </div>
</div>

**Figure 2.** Illustration of the subfolder structure

---

<div style="display: flex; justify-content: space-between; align-items: center; margin: 20px 0;">
  <div style="text-align: center; padding: 20px; background-color: #e6f2ff; border: 2px solid #0056b3; border-radius: 10px;">
    <h2>Overview of the AI-READI Dataset V3</h2>
    <div style="font-size: 3em; font-weight: bold; margin: 20px 0;">1000+</div>
    <p><strong>Accesses</strong></p>
    <p><strong>Access the dataset</strong><br>fairhub.io</p>
  </div>
  <div style="text-align: center; padding: 20px; background-color: #e6f2ff; border: 2px solid #0056b3; border-radius: 10px;">
    <div style="font-size: 2em; margin-bottom: 20px;">2,280</div>
    <p>participants</p>
    <div style="font-size: 2em; margin: 20px 0;">21M</div>
    <p>heart rate measurements</p>
    <div style="font-size: 2em; margin: 20px 0;">6M+</div>
    <p>glucose measurements</p>
  </div>
</div>

**Figure 3.** Overview of the AI-READI

---

<div style="background-color: #0056b3; color: white; padding: 20px; display: flex; justify-content: space-between; align-items: center;">
  <div>
    ![image](image_6.png)
    <p>This work is funded by NIH Common Fund’s Bridge2AI program (1OT2OD032644-01)</p>
  </div>
  <div>
    <p>Aydan Gasimova<br>agasimova@calmi2.org<br>aireadi.org<br>fairdataihub.org</p>
  </div>
</div>

level of a dataset structured following the CDS.

We are also developing pyfairdatatools, a Python package aimed at making it easier to implement the CDS.

We applied the CDS to the AI-READI dataset. AI-READI is one of the data generation projects supported by the NIH Bridge2AI program. The goal of the project is to collect multimodal dataset for studying Type 2 Diabetes and make it AI-ready.

While the dataset is extremely large and complex (Fig. 3), it has been downloaded and reused by over 1,000 researchers independently and led to many outcomes without intervention from the AI-READI team, demonstrating that the standard is supporting reusability.

## Conclusion

CDS provides a simple and intuitive way to organize clinical research data and metadata in line with the FAIR Principles.

Our evaluation on the AI-READI dataset confirmed the CDS aligns with all relevant FAIR Principles elements.

Independent reuse of the dataset also shows that the CDS addresses reusability issues.

Interoperability still needs to be validated by applying the CDS to other datasets and investigating how conveniently they can be combined and reused together.

Our immediate future effort is to promote the CDS, encourage its adoption, and improve based on external feedback.

We are also working on improving our tooling to facilitate implementation of the CDS further.

---

**view of the AI-READI dataset V3.**

<table>
  <tr>
    <td>280<br>icipants</td>
    <td>350k+<br>files</td>
    <td>3.8 TB<br>data</td>
  </tr>
  <tr>
    <td>21M<br>rt rate<br>irements</td>
    <td>950k+<br>lab measurements<br>and survey responses</td>
    <td>350k+<br>OCT volumes</td>
  </tr>
  <tr>
    <td>1M+<br>icose<br>irements</td>
    <td>150M+<br>air pollution and light<br>spectrometer<br>readings</td>
    <td>221k+<br>hours of sleep<br>recorded</td>
  </tr>
</table>

---

Bhavesh Patel  
bpatel@calmi2.org  
aireadi.org  
fairdataihub.org

Find this poster and all related references here  
→ https://bit.ly/CDS-2026

![image](image_1.png)