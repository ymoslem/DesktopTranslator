# Changelog


## v0.2.3

### Changed

- Updated dependencies, including CTranslate2 4.8.4 and NumPy 2.x; Python 3.11 or later is required

### Fixed

- Source language detection with NumPy 2
- Deprecated CTranslate2 result access
- Broken model download links


## v0.2.2 (2023-01-18, pre-release)

### Added

- NLLB-200 600M model download


## v0.2.1

### Added

- Source language detection
- macOS executable app

### Fixed

- Source language code as source prefix token
- Sentence splitting for non-Latin languages


## v0.2.0 (2022-02-07)

### Added

- Support for `M2M-100 models` (Fan et al., 2020)

### Fixed

- Save translation as UTF-8
- Respect paragraph format


## v0.1.0 (2022-01-04)

- First release of `DesktopTranslator`
