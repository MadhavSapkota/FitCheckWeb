# Play Store listing: recommended updates

For the owner to apply in Play Console. Not published (`seo-agent/` is excluded from the website).

## Privacy line (owner-approved wording)

Replace the current privacy line with:

> **Privacy:** Your photos are processed directly on your device.

This matches the website (homepage, How it works, AI Outfit Checker page). Use it where it describes outfit scoring
and fit checks. Keep the Google Play **Data safety** form consistent with how the app actually handles photos for every
feature, including AI image features (hairstyle try-on, outfit try-on, AI fashion images).

## Add to "More Style Tools"

List only features that are released in the current app version:

- Virtual outfit try-on: see AI images of yourself in different outfits
- AI fashion images and styling previews
- AI makeup assistant and live makeup try-on
- Live skin analysis: cosmetic skin overview (not medical advice)
- Live hair analysis for hairstyle and hair color ideas

Adding these makes the website's feature pages match the store listing and helps Play Store search.

## Website pages that still mention photo storage (unchanged)

- `index.html` privacy points: "Saved looks stay on your device", "Not stored by us / We don't keep or reuse your photos"
- `privacy.html`: unchanged by request; review it when convenient so it matches the wording above.

## Update, November 24, 2026: actions that need the app owner

Verified from the Android source and the live Play listing (see `PRIVACY-SOURCES.md`):

1. **Data safety form.** The listing declares no data collection or third-party sharing, but the app sends the photo you choose to Google Gemini, fal.ai and Black Forest Labs for Premium diagnostics, AI beauty/hair reports, hairstyle previews and try-on. Update the Data safety section in Play Console to match (photos shared with third-party AI services).
2. **Privacy policy URL.** The listing links `madhavsapkota.github.io/privatepolicy.github.io/`, a 2020 page that names another app. Point it to `https://fitcheck-fashion.com/privacy.html`.
3. **Provider retention.** Confirm each provider's retention and training terms for API traffic and add them to the privacy policy if you want to state them. The site makes no retention claims.
4. **Release match.** The source reviewed is dated up to 2026-06-25. Confirm that the Play build matches it, then re-check the website's privacy wording after any release that changes where photos go.
