---
name: commercial-product-storyboard
description: >-
  Deep analysis framework for transforming Product Descriptions, technical specs,
  and brand offers into high-converting commercial video storyboards (AIDA, PAS,
  Hero Reveal, Macro Spec Breakdown, and Viral Reels) in AniStory AI.
---

# Commercial & Product Description Storyboard Skill

Use this skill when analyzing product inputs (`product_name`, `description`, `specs`, `brand`, `pricing_offer`, `call_to_action`) and generating commercial storyboards in `ScriptAgent.deep_analyze_product_input`, `_build_advertisement_prompt`, and `_generate_offline_advertisement`.

## 1. Product DNA Extraction (`deep_analyze_product_input`)

Even when a user pastes an unstructured paragraph into **Product Description**, automatically extract:
1. **Product Category & Visual Lighting Profile**:
   - `audio_electronics` / `smart_gadgets`: Anodized aluminum/titanium textures, dark studio rim lighting, macro precision engineering shots.
   - `skincare_beauty`: Frosted glass/dropper textures, golden botanical serum droplets, soft diffused warm studio lighting.
   - `fashion_footwear`: Dynamic kinetic motion, carbon-weave/fabric macro textures, dramatic stadium/street rim lighting.
   - `kitchen_home`: Warm morning sunbeams, rich aromatic steam, crema/stainless steel reflections.
   - `luxury_accessory`: Velvet shadows, gold/sapphire specular highlights, slow motorized turntable macro shots.
2. **Customer Pain Point & Desire Hook**:
   - Identify the problem solved (e.g., noisy commutes, dull skin, slow mornings, soreness) to anchor **Scene 1 (The Hook)**.
3. **Top Unique Selling Propositions (USPs) & Quantitative Specs**:
   - Extract bullet points, numbers/units (`45dB`, `40-hour`, `185g`, `8K`, `100% organic`, `50% OFF`), and core benefits to showcase in **Scene 3 (Spec & Feature Proof)** and **Scene 4 (Lifestyle Transformation)**.
4. **Irresistible Offer & Call to Action (CTA)**:
   - Anchor the final scene with the exact pricing/discount offer and urgent CTA.

## 2. Commercial Arc Structures by `ad_style`

- `cinematic_commercial` (Apple / Nike): Hook Silhouette → Hero Reveal → Precision Macro Specs → Elevated Lifestyle → Iconic Brand Offer & CTA.
- `viral_reels` (TikTok / Shorts): 1.5s Pattern-Interrupt Hook → Instant Demo → 3 Rapid Spec Wins → Before/After Glow → Urgent Flash Offer CTA.
- `problem_solution` (PAS): Relatable Frustration → Hero Product Intervention → Mechanism in Action → Effortless Joy → Offer & CTA.
- `spec_breakdown` (Tech Deep-Dive): Industrial Design Overview → Core Architecture Macro → Performance Benchmark → Real-World Ergonomics → Specs Summary & CTA.
- `luxury_macro` (Rolex / Porsche): Moody Chiaroscuro Tease → Artisanal Material Macro → Craftsmanship in Motion → Prestige Lifestyle → Exclusive Invitation CTA.
