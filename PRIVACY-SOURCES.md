# FitCheck Android policy sources

Reviewed November 1, 2026.

## App-specific facts

- Official Android listing: https://play.google.com/store/apps/details?id=com.aistyleassistant.app
- Listing title: FitCheck: AI Fashion Stylist (verified live on 2026-11-24; an earlier note said "AI Outfit Planner"). Developer: Madhav Sapkota. It offers installation without a displayed purchase price and identifies ads and in-app purchases. No feature limits or exact purchase prices were inferred.
- Owner confirmation: photo processing is on-device; photos and saved outfits stay on the device and have no other use. Firebase is used.
- The listing's Data safety section currently declares no collection or third-party sharing. These are developer-provided declarations, not an independent inspection of installed SDK behavior.
- The listing does not identify the enabled Firebase services or the exact advertising SDK configuration. No Analytics, Crashlytics, Remote Config, or AdMob implementation is asserted as confirmed in the new pages.

## Public policy mismatch

The listing currently links to https://madhavsapkota.github.io/privatepolicy.github.io/ . That page names EnglishGrammar, is dated 2020, and mentions Google Play Services and AdMob. Because it names a different app, its SDK list was not treated as proof of FitCheck's actual SDKs. The new local FitCheck-specific privacy.html should be hosted and set as the app's Privacy Policy URL in Play Console. This local task does not change the external Play Console listing.

## Primary references

- Firebase service-specific data and retention: https://firebase.google.com/support/privacy
- Google Play privacy disclosures: https://support.google.com/googleplay/android-developer/answer/10144311
- Meaning of developer-provided Data safety labels: https://support.google.com/googleplay/answer/11416267
- Purchase terms: https://play.google.com/about/play-terms/index.html
- Refunds: https://support.google.com/googleplay/answer/2479637

The policy distinguishes locally stored photos from technical data that service providers may process. It does not invent precise SDK names, configured retention periods, consent controls, pricing, iOS plans, ratings, or testimonials. The exact service configuration remains an implementation fact that the public listing alone cannot establish.

## Android source review, November 24, 2026

Reviewed the Kotlin source in the FashionBeauty project (package `com.aistyleassistant.app`; source files dated up to 2026-06-25, so confirm that the released build matches).

- On device: face and outfit detection (ML Kit, MediaPipe) and the rule-based outfit score. The free-tier scan in `ScanScreen.kt` runs "on-device ML + rule-based analysis only".
- Sent to third parties: the Premium scan (`GeminiStyleAnalysisService`, downscaled photo to the Gemini API), the AI beauty and hair reports (`GeminiBeautyAnalysisService`), and hairstyle previews, try-on and image generation (`GeminiImagenService`, `FalAiImageService`, `BflAiImageService`). Photo bytes are sent as inline base64 data.
- Not verified: how long Google, fal.ai or Black Forest Labs retain photos (their own terms apply), whether a FitCheck-operated server exists, and whether Firebase is actually in the released build (the current Gradle files list no Firebase dependency).
- Mismatches to fix outside this repository: the Play Data safety section declares no third-party sharing, and the Play listing links an old privacy policy page that names a different app.
