# Clinical Dataset Structure: A Universal Framework for Structuring Clinical Research Datasets

Aydan Gasimova¹, Sanjay Soundarajan¹, Nayoon Gim²,³,⁴, Jamie Shaffer⁵, Julia Owen⁵, Aaron Lee⁵, Bhavesh Patel¹

¹FAIR Data Innovations Hub, California Medical Innovations Institute, San Diego, CA, USA
²Department of Ophthalmology, University of Washington, Seattle, WA, USA
³Department of Bioengineering, University of Washington, Seattle, WA, USA
⁴The Roger and Angie Karalis Johnson Retina Center, Seattle, WA, USA
⁵John F. Hardesty MD Department of Ophthalmology and Visual Sciences, Washington University, St. Louis, MO, USA

## Background

Each year, a rapidly growing volume of datasets is shared across the research community. In clinical studies, many data types are collected per participant, such as surveys, vital signs, eye images, and more. This data is expected to align with the FAIR (Findable, Accessible, Interoperable, Reusable) Principles.

## Problem

There is currently no consensus on how to organize multimodal data and include related information known as metadata. Standards like BIDS (Brain Imaging Data Structure) exist but only for structuring individual modalities. As a result, datasets from different studies are:

1. Not interoperable. The data cannot be directly combined with other datasets, workflows, and tools.
2. Not reusable. The data cannot be easily used by researchers other than the original creators.

Original researchers. Unorganized data and metadata. New researchers.

## Purpose

The purpose of this work was to develop a standard for organizing clinical research data and associated metadata.

## Methods

1. Review and analyze existing standards for organizing specific datatypes (e.g. Brain Imaging Data Structure) and popular metadata schemas (e.g. DataCite and ClinicalTrials.gov)
2. Review and analyze AI/ML-specific data documentation practices (e.g. datasheet and healtsheet)
3. Combine review findings and our understanding of clinical research data for establishing the standard
4. Apply the standard to a real world dataset as a test case.

Figure 1. Illustration of the root level of a dataset structured following the CDS.

cardiac_ecg, retinal_oct: Folders of the datatypes present in the dataset.
README.md, LICENSE.txt, healthsheet.md, CHANGELOG.md: Metadata files containing information about the dataset in a human-friendly format.
study_description.json, dataset_description.json, datatype_dictionary.json, participants.tsv, participants.json: Metadata files containing information about the dataset in a machine-friendly format.

Figure 2. Illustration of the subfolder structure prescribed by the CDS.

datatype folder(s) to modality folder(s) to device folder(s) to participant folder(s).

Figure 3. Overview of the AI-READI dataset V3.

Overview of the AI-READI Dataset V3: 1000+ Accesses. 2,280 participants. 350k+ files. 3.8 TB data. 21M heart rate measurements. 950k+ lab measurements and survey responses. 350k+ OCT volumes. 6M+ glucose measurements. 150M+ air pollution and light spectrometer readings. 221k+ hours of sleep recorded. Access the dataset fairhub.io.

## Results

We established the Clinical Dataset Structure (CDS) a standard for organizing clinical research data and metadata.

The CDS provides several specifications:

The CDS instructs to organize data into one folder per datatype at the root level (Fig. 1). It also prescribes a specific structure within each datatype folder (Fig 2).

The CDS requires several metadata files to be included at the root-level that contain essential information for reusing the dataset (Fig. 1).

Collectively, the metadata files capture 80+ metadata fields including dataset description, study information, license terms, and more.

The CDS also provides specification for naming the different folders and files consistently.

The full specification is available at cds-specification.readthedocs.io.

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

## Contact

This work is funded by NIH Common Fund's Bridge2AI program (1OT2OD032644-01)

Aydan Gasimova, agasimova@calmi2.org, aireadi.org, fairdataihub.org
Bhavesh Patel, bpatel@calmi2.org, aireadi.org, fairdataihub.org

Find this poster and all related references here: https://bit.ly/CDS-2026
