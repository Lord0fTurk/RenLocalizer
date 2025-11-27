"""
Simple RenPy Parser - Working Version
"""

import re
import logging
from pathlib import Path
from typing import Set, Union, List, Dict, Any
import chardet

class RenPyParser:
    def __init__(self, config_manager=None):
        self.logger = logging.getLogger(__name__)
        self.config = config_manager
        
        # Core dialogue patterns
        self.char_dialog_re = re.compile(r'^(?P<indent>\s*)(?P<char>[A-Za-z_]\w*)\s+(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')')
        self.narrator_re = re.compile(r'^(?P<indent>\s*)(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')\s*(?:#.*)?$')
        
        # Menu and choice patterns - IMPROVED for conditional choices
        self.menu_choice_re = re.compile(r'^\s*(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')\s*(?:if\s+[^:]+)?\s*:\s*')
        self.menu_title_re = re.compile(r'^\s*menu\s*(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')?:')
        
        # UI element patterns
        self.screen_text_re = re.compile(r'^\s*(?:text|label|tooltip)\s+(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')')
        self.textbutton_re = re.compile(r'^\s*textbutton\s+(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')')
        
        # Config and GUI patterns  
        self.config_string_re = re.compile(r'^\s*config\.(?:name|version|about|menu_|window_title|save_name)\s*=\s*(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')')
        self.gui_text_re = re.compile(r'^\s*gui\.(?:text|button|label|title|heading|caption|tooltip|confirm)(?:_[a-z_]*)?(?:\[[^\]]*\])?\s*=\s*(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')')          # Style property assignments
        self.style_property_re = re.compile(r'^\s*style\s*\.\s*[a-zA-Z_]\w*\s*=\s*(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')')
        
        # Python expressions with $ prefix
        self.python_renpy_re = re.compile(r'^\s*\$\s+.*?(?:renpy\.)?(?:input|notify)\s*\([^)]*?(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')')
        
        # RenPy function calls
        self.renpy_function_re = re.compile(r'^\s*(?:renpy\.)?(?:input|notify)\s*\([^)]*?(?P<quote>"(?:[^"\\]|\\.)*"|\'(?:[^\\\']|\\.)*\')')
        
        # Technical terms to exclude
        self.renpy_technical_terms = {
            'left', 'right', 'center', 'top', 'bottom', 'gui', 'config',
            'true', 'false', 'none', 'auto', 'png', 'jpg', 'mp3', 'ogg'
        }
        
    def extract_translatable_text(self, file_path: Union[str, Path]) -> Set[str]:
        """Extract translatable text from a .rpy file."""
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read()
                detected = chardet.detect(raw_data)
                encoding = detected.get('encoding', 'utf-8')
            
            with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
                content = f.read()
            
            lines = content.splitlines()
            translatable_texts = set()
            
            for line_num, line in enumerate(lines, 1):
                patterns = [
                    self.char_dialog_re,
                    self.narrator_re,
                    self.menu_choice_re,
                    self.menu_title_re,
                    self.screen_text_re,
                    self.textbutton_re,
                    self.config_string_re,
                    self.gui_text_re,
                    self.style_property_re,
                    self.python_renpy_re,
                    self.renpy_function_re
                ]
                
                for pattern in patterns:
                    match = pattern.match(line)
                    if match:
                        for group_name in match.groupdict():
                            if 'quote' in group_name and match.group(group_name):
                                text = self._extract_string_content(match.group(group_name))
                                if text and self.is_meaningful_text(text):
                                    translatable_texts.add(text)
                        break
                        
            return translatable_texts
            
        except Exception as e:
            self.logger.error(f"Error parsing {file_path}: {e}")
            return set()
    
    def _extract_string_content(self, quoted_string: str) -> str:
        """Extract content from a quoted string."""
        if not quoted_string:
            return ""
        
        if quoted_string.startswith('"') and quoted_string.endswith('"'):
            content = quoted_string[1:-1]
        elif quoted_string.startswith("'") and quoted_string.endswith("'"):
            content = quoted_string[1:-1]
        else:
            content = quoted_string
        
        content = content.replace('\\"', '"').replace("\\'", "'")
        content = content.replace('\\n', '\n').replace('\\t', '\t')
        
        return content.strip()
    
    def is_meaningful_text(self, text: str) -> bool:
        """Check if text is meaningful dialogue/story content."""
        if not text or len(text.strip()) < 2:
            return False
        
        text_lower = text.lower().strip()
        
        if text_lower in self.renpy_technical_terms:
            return False

        # Skip pure placeholder-only strings (e.g. only [player_name] or only {var})
        # Such strings have no visible user-facing text.
        if re.fullmatch(r"\s*(\[[^\]]+\]|\{[^}]+\}|%s|%\([^)]+\)[sdif])\s*", text):
            return False
        
        # IMPROVED: Skip technical patterns
        technical_patterns = [
            r'^#[0-9a-fA-F]+$',  # Color codes
            r'\.ttf$',           # Font files
            r'^%s[%\s]*$',       # %s patterns
            r'fps|renderer|ms$', # Performance metrics
            r'^[0-9.]+$',        # Pure numbers
            r'game_menu|sync|input|overlay', # UI technical terms
            r'vertical|horizontal|linear',   # Layout terms
            r'touch_keyboard|subtitle|empty' # More technical terms
        ]
        
        for pattern in technical_patterns:
            if re.search(pattern, text_lower):
                return False
        
        if any(ext in text_lower for ext in ['.png', '.jpg', '.mp3', '.ogg']):
            return False
        
        # Skip pure numbers but allow version numbers (contain dots)
        if re.match(r'^[-+]?\d+$', text.strip()):
            return False
        
        # Allow version-like strings (numbers with dots, e.g., "1.0.0", "2.1")
        if re.match(r'^\d+(?:\.\d+)+$', text.strip()):
            return True
        
        if re.search(r'[a-zA-ZçğıöşüÇĞIİÖŞÜ]', text) and len(text.strip()) >= 2:
            return True
        
        return False
    
    def determine_text_type(self, text: str, context_line: str = "") -> str:
        """Determine the type of text based on content and context."""
        if not context_line:
            return 'dialogue'
        
        context_lower = context_line.lower()
        
        if 'textbutton' in context_lower:
            return 'button'
        elif 'menu' in context_lower:
            return 'menu'
        elif 'screen' in context_lower:
            return 'ui'
        elif 'config.' in context_lower:
            return 'config'
        elif 'gui.' in context_lower:
            return 'gui'
        elif 'style.' in context_lower:
            return 'style'
        elif 'renpy.' in context_lower or ' notify(' in context_lower or ' input(' in context_lower:
            return 'renpy_func'
        else:
            return 'dialogue'
    
    def parse_directory(self, directory: Union[str, Path]) -> List[dict]:
        """Parse all .rpy files in a directory and return formatted text data.

        Honors type-based translation filters and never-translate rules if
        a ConfigManager instance was provided at construction time.
        """
        directory = Path(directory)
        results = []
        # Find all .rpy files, ama 'game/tl/' içerenleri hariç tut
        rpy_files = [f for f in directory.glob("**/*.rpy") if "game/tl/" not in str(f).replace('\\', '/')]
        self.logger.info(f"Found {len(rpy_files)} .rpy files in {directory} (excluding game/tl/)")
        for rpy_file in rpy_files:
            try:
                # Extract texts from file
                extracted_texts = self.extract_translatable_text(rpy_file)
                # Read file content to get line numbers
                with open(rpy_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                # Convert to GUI format
                for text in extracted_texts:
                    # Try to find line number and context
                    line_number = 1
                    context = ""
                    character = ""
                    # Search for the text in file lines to get context
                    for i, line in enumerate(lines):
                        if text in line:
                            line_number = i + 1
                            context = line.strip()
                            # Try to extract character name if it's dialogue
                            if '"' in line or "'" in line:
                                char_match = re.match(r'\s*([A-Za-z_]\w*)\s+["\']', line.strip())
                                if char_match:
                                    character = char_match.group(1)
                            break
                    # Determine text type based on context
                    text_type = self.determine_text_type(text, context)

                    # Apply type-based filters and never-translate rules
                    if not self._should_translate_text(text, text_type):
                        continue
                    text_data = {
                        'text': text,
                        'type': text_type,
                        'file_path': str(rpy_file),
                        'line_number': line_number,
                        'character': character,
                        'context': context
                    }
                    results.append(text_data)
            except Exception as e:
                self.logger.error(f"Error parsing file {rpy_file}: {e}")
        self.logger.info(f"Total extracted texts: {len(results)}")
        return results

    def _should_translate_text(self, text: str, text_type: str) -> bool:
        """Decide whether a text should be translated based on type and rules."""
        # If no config provided, keep legacy behavior
        if self.config is None:
            return True

        # 1) Type-based filters from TranslationSettings
        ts = self.config.translation_settings
        if text_type == 'dialogue' and not ts.translate_dialogue:
            return False
        if text_type == 'menu' and not ts.translate_menu:
            return False
        if text_type == 'ui' and not ts.translate_ui:
            return False
        if text_type == 'config' and not ts.translate_config_strings:
            return False
        if text_type == 'gui' and not ts.translate_gui_strings:
            return False
        if text_type == 'style' and not ts.translate_style_strings:
            return False
        if text_type == 'renpy_func' and not ts.translate_renpy_functions:
            return False

        # 2) never_translate.json rules (exact / contains / regex)
        rules: Dict[str, Any] = getattr(self.config, 'never_translate_rules', {}) or {}
        text_strip = text.strip()

        try:
            # Exact matches
            for val in rules.get('exact', []) or []:
                if text_strip == val:
                    return False

            # Contains
            for val in rules.get('contains', []) or []:
                if val and val in text_strip:
                    return False

            # Regex
            import re
            for pattern in rules.get('regex', []) or []:
                try:
                    if re.search(pattern, text_strip):
                        return False
                except re.error:
                    # Ignore invalid patterns
                    continue
        except Exception as e:
            self.logger.warning(f"never_translate rules failed: {e}")

        return True
    
    def extract_from_directory_parallel(self, directory: Union[str, Path], recursive: bool = True, max_workers: int = 4):
        """Extract texts from all .rpy files in parallel (for compatibility with GUI)."""
        directory = Path(directory)
        results = {}
        # Find all .rpy files, ama 'game/tl/' içerenleri hariç tut
        if recursive:
            rpy_files = [f for f in directory.glob("**/*.rpy") if "game/tl/" not in str(f).replace('\\', '/')]
        else:
            rpy_files = [f for f in directory.glob("*.rpy") if "game/tl/" not in str(f).replace('\\', '/')]
        self.logger.info(f"Found {len(rpy_files)} .rpy files for parallel processing (excluding game/tl/)")
        
        # For now, use sequential processing but return the expected format
        for rpy_file in rpy_files:
            try:
                extracted_texts = self.extract_translatable_text(rpy_file)
                results[rpy_file] = extracted_texts
            except Exception as e:
                self.logger.error(f"Error processing file {rpy_file}: {e}")
                results[rpy_file] = set()
        
        total_texts = sum(len(texts) for texts in results.values())
        self.logger.info(f"Parallel processing completed: {len(results)} files, {total_texts} total texts")
        return results
    
    def preserve_placeholders(self, text: str):
        """
        Preserve placeholders in text during translation.
        Returns tuple of (processed_text, placeholder_map)
        """
        if not text:
            return text, {}
        
        placeholder_map = {}
        processed_text = text
        placeholder_counter = 0
        
        # RenPy variable placeholders like [variable_name]
        renpy_var_pattern = r'\[([^\]]+)\]'
        for match in re.finditer(renpy_var_pattern, text):
            # Use NUMBERS ONLY to prevent translation engines from translating
            placeholder_id = f"XYZ{placeholder_counter:03d}"
            placeholder_map[placeholder_id] = match.group(0)
            processed_text = processed_text.replace(match.group(0), placeholder_id, 1)
            placeholder_counter += 1
        
        # RenPy text tags like {color=#ff0000}, {/color}, {b}, {/b}, etc.
        renpy_tag_pattern = r'\{[^}]*\}'
        for match in re.finditer(renpy_tag_pattern, text):
            # Use NUMBERS ONLY to prevent translation engines from translating
            placeholder_id = f"XYZ{placeholder_counter:03d}"
            placeholder_map[placeholder_id] = match.group(0)
            processed_text = processed_text.replace(match.group(0), placeholder_id, 1)
            placeholder_counter += 1
        
        # Python-style format strings like %(variable)s, %s, %d, etc.
        python_format_pattern = r'%\([^)]+\)[sdif]|%[sdif]'
        for match in re.finditer(python_format_pattern, text):
            # Use NUMBERS ONLY to prevent translation engines from translating
            placeholder_id = f"XYZ{placeholder_counter:03d}"
            placeholder_map[placeholder_id] = match.group(0)
            processed_text = processed_text.replace(match.group(0), placeholder_id, 1)
            placeholder_counter += 1
        
        # Python 3.6+ f-string style placeholders like {variable}
        fstring_pattern = r'\{[^}]+\}'
        for match in re.finditer(fstring_pattern, processed_text):  # Use processed_text to avoid double replacement
            # Skip if already replaced by RenPy tag pattern
            if not match.group(0).startswith('XYZ'):
                # Use NUMBERS ONLY to prevent translation engines from translating
                placeholder_id = f"XYZ{placeholder_counter:03d}"
                placeholder_map[placeholder_id] = match.group(0)
                processed_text = processed_text.replace(match.group(0), placeholder_id, 1)
                placeholder_counter += 1
        
        return processed_text, placeholder_map
    
    def restore_placeholders(self, translated_text: str, placeholder_map: dict) -> str:
        """
        Restore placeholders in translated text.
        """
        if not translated_text or not placeholder_map:
            return translated_text
        
        import re
        restored_text = translated_text
        
        # First try exact match
        for placeholder_id, original_placeholder in placeholder_map.items():
            restored_text = restored_text.replace(placeholder_id, original_placeholder)
        
        # Try with various corruptions that translation engines might introduce
        for placeholder_id, original_placeholder in placeholder_map.items():
            # Handle case changes, spaces, and common corruptions
            corrupted_patterns = [
                # Case variations
                placeholder_id.lower(),                    # xyz000
                placeholder_id.upper(),                    # XYZ000
                placeholder_id.capitalize(),               # Xyz000
                placeholder_id.replace('XYZ', 'Xyz'),      # Xyz000
                placeholder_id.replace('XYZ', 'xyz'),      # xyz000
                
                # Space variations
                placeholder_id.replace('XYZ', 'XYZ '),     # XYZ 000
                placeholder_id.replace('XYZ', ' XYZ'),     # Space before
                placeholder_id.replace('XYZ', ' XYZ '),    # Spaces around
                placeholder_id.replace('XYZ', 'Xyz '),     # Xyz 000
                placeholder_id.replace('XYZ', 'xyz '),     # xyz 000
                
                # Multiple space variations
                placeholder_id.replace('XYZ', 'X Y Z'),    # X Y Z000
                placeholder_id.replace('XYZ', 'x y z'),    # x y z000
            ]
            
            for pattern in corrupted_patterns:
                # Try both exact and with spaces around
                restored_text = restored_text.replace(pattern, original_placeholder)
                restored_text = restored_text.replace(f" {pattern} ", f" {original_placeholder} ")
                restored_text = restored_text.replace(f" {pattern}", f" {original_placeholder}")
                restored_text = restored_text.replace(f"{pattern} ", f"{original_placeholder} ")
        
        # Handle very corrupted cases with regex - more aggressive approach
        for placeholder_id, original_placeholder in placeholder_map.items():
            # Extract the number from XYZ000 pattern
            if placeholder_id.startswith('XYZ'):
                number_part = placeholder_id[3:]  # Get "000" part
                
                # Create multiple regex patterns for different corruptions
                patterns = [
                    # Standard corruptions
                    r'\b\s*[Xx][Yy][Zz]\s*' + number_part + r'\s*\b',
                    # With spaces in XYZ
                    r'\b\s*[Xx]\s*[Yy]\s*[Zz]\s*' + number_part + r'\s*\b',
                    # Just the number when XYZ gets completely corrupted
                    r'\b(?:XYZ|Xyz|xyz|X Y Z|x y z)\s*' + number_part + r'\b',
                    # More aggressive - any 3 letters followed by the number
                    r'\b[A-Za-z]{3}\s*' + number_part + r'\b'
                ]
                
                for pattern in patterns:
                    restored_text = re.sub(pattern, original_placeholder, restored_text, flags=re.IGNORECASE)
        
        return restored_text
