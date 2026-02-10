"""
关键词匹配引擎
"""
import re
from typing import List, Dict, Any, Optional


class KeywordMatcher:
    """关键词匹配器"""

    def __init__(self, keywords_config: Dict[str, Any]):
        """
        初始化关键词匹配器

        Args:
            keywords_config: 关键词配置
        """
        self.exact_keywords = keywords_config.get('exact', [])
        self.contains_keywords = keywords_config.get('contains', [])
        self.regex_patterns = []

        # 编译正则表达式
        for pattern in keywords_config.get('regex', []):
            try:
                self.regex_patterns.append(re.compile(pattern))
            except re.error as e:
                print(f"警告: 正则表达式编译失败: {pattern}, 错误: {e}")

    def match(self, text: str) -> Optional[str]:
        """
        匹配文本中的关键词

        Args:
            text: 要匹配的文本

        Returns:
            匹配到的关键词，如果没有匹配则返回 None
        """
        if not text:
            return None

        # 1. 精确匹配
        for keyword in self.exact_keywords:
            if text == keyword:
                return keyword

        # 2. 模糊匹配（包含）
        for keyword in self.contains_keywords:
            if keyword in text:
                return keyword

        # 3. 正则表达式匹配
        for pattern in self.regex_patterns:
            match = pattern.search(text)
            if match:
                return match.group(0)

        return None

    def match_all(self, text: str) -> List[str]:
        """
        匹配文本中的所有关键词

        Args:
            text: 要匹配的文本

        Returns:
            所有匹配到的关键词列表
        """
        if not text:
            return []

        matched_keywords = []

        # 1. 精确匹配
        for keyword in self.exact_keywords:
            if text == keyword:
                matched_keywords.append(keyword)

        # 2. 模糊匹配（包含）
        for keyword in self.contains_keywords:
            if keyword in text:
                matched_keywords.append(keyword)

        # 3. 正则表达式匹配
        for pattern in self.regex_patterns:
            matches = pattern.findall(text)
            matched_keywords.extend(matches)

        return matched_keywords
