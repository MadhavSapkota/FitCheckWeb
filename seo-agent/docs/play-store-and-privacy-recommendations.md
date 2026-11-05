# Play Store listing and privacy policy: recommended updates

Prepared 2026-11-05 for owner review. **Nothing here is applied automatically.** `privacy.html` and the Play
listing are unchanged. This folder is excluded from the website (`_config.yml` excludes `seo-agent/`).

## Why

The current Play listing says: *"Your photos are processed on your device and are never stored or uploaded by us."*
The owner has confirmed the app **generates photos** (hairstyle try-on, outfit try-on, AI fashion images), which
means those features process photos online. The listing statement is therefore at least incomplete. The listing also
omits several features the website now describes, which makes those website claims hard to verify.

## 1. Facts to confirm before changing any text

Answer these from the app code and your AI provider's terms. Do not publish any of the wording in sections 2 and 3
until they are answered.

| # | Question | Answer |
|---|---|---|
| 1 | Which features send a photo off the device? (outfit score, live FitCheck, makeup, hair try-on, hair analysis, skin analysis, outfit try-on, AI images) | |
| 2 | Which service or provider receives them? | |
| 3 | Does the app's own server store photos or generated images? For how long? | |
| 4 | Does the AI provider retain inputs or outputs, or use them for training? (check its API data policy) | |
| 5 | Is the transfer encrypted in transit (HTTPS)? | |
| 6 | Where are saved looks / the digital closet stored: on the device only, or synced? | |
| 7 | Can users delete their data, and how? | |
| 8 | Are live skin analysis, live hair analysis, live makeup try-on and live outfit check implemented and released? | |

## 2. Play Store listing: suggested text

Placeholders in `[brackets]` must be filled from section 1.

**Add to "More Style Tools"** (only for features confirmed in Q8):

- Virtual outfit try-on: see AI-generated images of yourself in different outfits
- AI fashion images and styling previews from your photo
- Live makeup try-on and AI makeup feedback
- Live skin analysis: a cosmetic AI skin overview (not medical advice)
- Live hair analysis for hairstyle and hair color ideas

**Replace the privacy line with:**

> Privacy: Outfit scoring runs on your device. AI image features such as hairstyle and outfit try-on send your photo
> to [provider / our server] to create the image. [Retention statement from Q3–Q4.] See our privacy policy for details.

**Google Play Data safety form:** update "Photos" (collected / shared / processed ephemerally / optional) to match
Q1–Q7. It must agree with the listing and the privacy policy.

## 3. Privacy policy (`privacy.html`): suggested section

Add only after section 1 is answered:

> **Photos and AI features.** Outfit scoring runs on your device. When you use AI image features (hairstyle try-on,
> outfit try-on, AI fashion images) [and live analysis features, if applicable], your photo is sent to [provider] to
> process the request [over an encrypted connection: confirm Q5]. [We do / do not store these photos: Q3.]
> [Provider retention: Q4.] Saved looks are stored [location: Q6]. You can [deletion method: Q7].
> Skin and hair analysis provide cosmetic suggestions only and are not medical advice.

## 4. Website wording already made safe

- Landing pages make **no** statements about photo storage, retention, deletion or encryption.
- They say only: "Outfit scoring runs on your device" and "AI image features use online processing."
- The content generator (`app_facts.yaml`) and the article quality gate now block storage, retention, deletion and
  encryption claims until these facts are confirmed.

## 5. Existing pages to review together with section 3 (not changed in PR #1)

These statements were written before the owner confirmed online AI image generation. Some may be inaccurate for the
AI features:

| Page | Statement | Concern |
|---|---|---|
| `how-it-works.html` | "Your photos stay on your device" | Likely false for AI image features (photos are sent online) |
| `index.html` | "We don't store your photos or use them for anything else" / "Not stored by us" | Must match Q3–Q4 (provider retention too) |
| `index.html` | "Saved looks stay on your device" / "saved outfits stay there" | Confirm with Q6 |
| `privacy.html` | "Saved outfit photos and related local app data remain on your device" | Confirm with Q6; add the AI-feature section |
| `privacy.html` | "Our on-device photos and saved outfits are not sent to Firebase" | True only for on-device features; the AI features need disclosure |
| Play listing | "processed on your device and are never stored or uploaded by us" | Incomplete for AI image features |
