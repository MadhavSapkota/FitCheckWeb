# FitCheck AI landing page

Open index.html directly. It is a self-contained page with embedded Inter fonts, images, styles, and scripts. Upload index.html, privacy.html, and terms.html together, or use fitcheck-upload.zip, which contains all three pages. Fonts, styles, and images remain embedded in each page.

The hero now uses the original supplied girl and boy street-style photos side by side, with complete framing. The result-screen phone mockup and its score badge have been removed.

## Restored original backgrounds

The original saved page was used as the source:

- Main canvas: #FFF9FB.
- Hero and steps: linear-gradient(135deg,#FFF7EF 0%,#FFF0F2 54%,#FCEBF2 100%).
- Final CTA: linear-gradient(120deg,#FFE0C9 0%,#FE9AA6 54%,#F5BDD2 100%).

The original light appearance is the default. Dark mode is an explicit optional toggle, rather than an automatic change to the original background.

## Full outfit collection

All 16 original supplied photographs are restored in the original order, with complete-photo framing. Source captions, embedded text, and credits are preserved. Original source files remain unchanged. Existing 720px derivatives are embedded when available; smaller sources are not enlarged.

The collection initially shows eight outfits. Show More reveals the remaining outfits and moves keyboard focus to the first newly revealed photo. Filters support All looks, Everyday, Going out, and Active. Without JavaScript, all photographs remain visible. The Outfit collection navigation link is visible on mobile as well as desktop. Selecting a photograph opens its complete embedded image in an accessible dialog.

## Editable placeholders

Android availability, free-download pricing, photo handling, and terms are now described without visitor-facing draft questions. Collection cards do not claim outfit scores.

## Verification

Browser checks passed at 320, 375, 600, 768, 960, 1280, and 1440px without horizontal overflow. Checks also covered the restored background gradients, all 16 collection entries, Show More and focus, all four filters, theme switching, photo dialog focus and Escape, FAQ keyboard activation, Terms disclosure, reduced motion, and embedded image decoding.

The page retains supplied photography and the Inter license; see PHOTO-CREDITS.md and assets/fonts/OFL.txt. The font license is embedded in the HTML as a comment.

Below-the-fold images use lazy loading. Because their bytes are embedded in the HTML, this defers decoding/rendering rather than network transfer.

To regenerate the upload archive, run python3 tools/package-site.py.

## Privacy Policy

privacy.html is linked from the hero, photo FAQ, and footer. It states the owner-confirmed facts: photo analysis happens on-device, photos and saved outfits stay locally, and photos are not collected or used for other purposes. It separately discloses the confirmed use of Firebase. Firebase and advertising are explained separately from on-device photos without claiming a specific unverified SDK configuration. Do not turn the photo-specific statement into a blanket no-data-collection claim. The policy links to official Firebase and Google privacy information.

## Android listing research

The Android FAQs, policy pages, and Terms of Service were updated from the official Google Play listing and the owner-confirmed on-device storage. Terms of Service is linked as terms.html. Public sources and remaining implementation limits are recorded in PRIVACY-SOURCES.md. The listing currently links to an older policy naming EnglishGrammar; after hosting the new page, update the Play Console privacy URL to the hosted privacy.html URL.

## Makeup Assistant

A dedicated Makeup Assistant section sits between How it works and the outfit collection, linked from the main navigation. It introduces the app’s existing beauty/makeup checks, offers photo-preparation tips, uses the same Google Play CTA and confirmed on-device privacy statement, and retains the existing palette, light/dark themes, and original photography. No virtual makeup try-on, shade-matching, medical, or fabricated product-result claims are added.

The Makeup Assistant section now includes all three supplied beauty photos, in a three-column desktop gallery and a single-column mobile gallery. Images are lazy-loaded, retain their full framing and original source text, and open in accessible full-photo dialogs. The original PNGs remain in assets/makeup/originals/.

The Makeup Assistant section is now photo-led: one short headline and description, a Google Play CTA, and three brief labels over the photos. The preparation-tips panel and long photo descriptions were removed. Captions use a dark bottom scrim with white type for legibility; full-photo dialogs remain available.

## Hairstyle Looks

A separate, photo-led Hairstyle Looks section follows Makeup Assistant and is linked as Hair in the navigation. All three supplied images keep their complete portrait/collage framing and open in the existing accessible full-photo dialog. The first promotional graphic retains its embedded source text and controls as part of the image; it is not a live website widget. Original files are preserved in assets/hairstyles/originals/. Existing hero photos, all 16 outfit photos, three makeup photos, and original background gradients remain intact.

The Hairstyle Looks promotional graphic has been replaced by the supplied layered-hair collage, labeled Layers & movement. All three hairstyle cards use equal-width columns and preserve their complete square images.

The landing-page CTA notes now say Available for Android. Ads and in-app-purchase labels were removed from the marketing page and its download FAQ. Verified advertising/payment disclosures remain in privacy.html and terms.html.

Outfit category filters are displayed as clickable hashtags: #FitCheck (all), #FashionStyle (everyday), #GoingOut, and #Activewear. They filter the local photo collection, preserve pressed states and result counts, and retain the Show More interaction.

Hairstyle Looks now contains four images, including the supplied Blonde waves photo. The layout uses one column on mobile, two on tablet, and four on wide desktop screens. All cards open in the full-photo viewer.

The How it works section was compacted into three clear actions: Upload a photo, See your score, and Save the look. Repeated labels and the extra hair/makeup strip were removed; numbered cards, restrained connectors, and one privacy-aware download bar provide the hierarchy. The original background gradient is preserved.

The How it works section now uses a soft neutral ivory background (#F3F0E9), with a coordinating dark-theme background (#29252A). Other section backgrounds are preserved.

## Illustrated How it works redesign

The current section uses #F1EFEA, matching white cards, #762F4A accents, smaller headings, and directly grouped subtext. Three HTML/SVG mini previews illustrate upload, an example 86/100 result with Fit/Color/Balance bars, and a four-look closet. All three cards have the same treatment. Dashed connectors switch from horizontal to vertical when cards stack. The burgundy CTA includes a readable on-device privacy message, a soft pink Google Play button, and the owner-requested iOS coming soon note. The requested time/detail copy is included. how-it-works.html is a separate self-contained section deliverable with embedded Inter fonts and no external rendering dependencies; the same section is integrated in index.html.

## Compact Android hero

The hero now uses a small AI outfit scoring for Android pill, a three-line Inter headline reduced to a 52px maximum, darker description text, a burgundy Google Play CTA with Free on Android, and one consolidated photo-privacy line. The feature checklist uses 15px dark text. The cut-off third checklist item was completed as Your style, your call to avoid duplicating the privacy statement. Original girl/boy photos remain top-aligned in the desktop 55/45 split and follow the text on mobile. The hero gradient is #FFF5F3 to #FCEFF1. hero.html is a self-contained deliverable with embedded fonts/photos and an inline Privacy Policy reachable from its link. The same hero is integrated into index.html.

The hero uses original brand pink #FE9AA6 for its primary Google Play button, with dark plum text. Hero headline accents, links, and icons use a deeper readable pink #AF2E61; the blush-to-cream background and original photos remain intact. Both index.html and the standalone hero.html reflect this update.
