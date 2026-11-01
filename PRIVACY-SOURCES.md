# FitCheck Android policy sources

Reviewed November 1, 2026.

## App-specific facts

- Official Android listing: https://play.google.com/store/apps/details?id=com.aistyleassistant.app
- Listing title: FitCheck: AI Outfit Planner. Developer: Madhav Sapkota. It offers installation without a displayed purchase price and identifies ads and in-app purchases. No feature limits or exact purchase prices were inferred.
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
