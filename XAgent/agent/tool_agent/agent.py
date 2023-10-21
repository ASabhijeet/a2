import json
import json5
import jsonschema
from typing import List
from colorama import Fore

from XAgent.agent.base_agent import BaseAgent
from XAgent.utils import RequiredAbilities
from XAgent.message_history import Message
from XAgent.logs import logger
from XAgent.data_structure.node import ToolNode
from XAgent.ai_functions import function_manager,objgenerator
from XAgent.config import CONFIG

class ToolAgent(BaseAgent):
    abilities = set([RequiredAbilities.tool_tree_search])
    
    def parse(
        self,
        placeholders: dict = {},
        arguments:dict=None,
        functions=None,
        function_call=None,
        stop=None,
        additional_messages: List[Message] = [],
        additional_insert_index: int = -1,
        *args,
        **kwargs
    ):
        prompt_messages = self.fill_in_placeholders(placeholders)
        
        # Temporarily disable the arguments for openai
        if self.config.default_request_type == 'openai':
            arguments = None
            if CONFIG.enable_ask_human_for_help:
                functions += [function_manager.get_function_schema('ask_human_for_help')]
            prompt_messages[0].content += '\n--- Avaliable Tools ---\n{}'.format(json.dumps(functions,indent=2))
            functions = [function_manager.get_function_schema('subtask_submit'),
                         function_manager.get_function_schema('subtask_handle')]
            
        messages = prompt_messages[:additional_insert_index] + additional_messages + prompt_messages[additional_insert_index:]

        message,tokens = self.generate(
            messages=messages,
            arguments=arguments,
            functions=functions,
            function_call=function_call,
            stop=stop,
            *args,**kwargs
        )

        function_call_args:dict = message['function_call']['arguments']

        # for tool_call, we need to validate the tool_call arguments if exising
        if self.config.default_request_type == 'openai' and 'tool_call' in function_call_args:
            tool_schema = function_manager.get_function_schema(function_call_args['tool_call']["tool_name"])
            assert tool_schema is not None, f"Function {function_call_args['tool_call']['tool_name']} not found! Poential Schema Validation Error!"
            
            tool_call_args = function_call_args['tool_call']['tool_input'] if 'tool_input' in function_call_args['tool_call'] else ''
            
            def validate():
                nonlocal tool_schema,tool_call_args
                if isinstance(tool_call_args,str):
                    tool_call_args = {} if tool_call_args == '' else json5.loads(tool_call_args)
                jsonschema.validate(instance=tool_call_args, schema=tool_schema['parameters'])
                    
            try:
                validate()
            except Exception as e:  
                tool_call_args = objgenerator.dynamic_json_fixs(
                    broken_json=tool_call_args,
                    function_schema=tool_schema,
                    messages=messages,
                    error_message=str(e))["choices"][0]["message"]["function_call"]["arguments"]
                validate()
                function_call_args['tool_call']['tool_input'] = tool_call_args
            
            message['function_call'] = function_call_args.pop('tool_call')
            message['function_call']['name'] = message['function_call'].pop('tool_name')
            message['function_call']['arguments'] = message['function_call'].pop('tool_input')
            message['arguments'] = function_call_args
                
        return message,tokens
    
    def message_to_tool_node(self,message) -> ToolNode:
        # assume message format
        # {
        #   "content": "The content is useless",
        #   "function_call": {
        #       "name": "xxx",
        #       "arguments": "xxx"
        #  },
        #  "arguments": {
        #      "xxx": "xxx",
        #      "xxx": "xxx"   
        #  },
        # }
        
        new_node = ToolNode()
        if "content" in message.keys():
            print(message["content"])
            new_node.data["content"] = message["content"]
        if 'arguments' in message.keys():
            new_node.data['thoughts']['properties'] = message["arguments"]
        if "function_call" in message.keys():
            new_node.data["command"]["properties"]["name"] = message["function_call"]["name"]
            new_node.data["command"]["properties"]["args"] = message["function_call"]["arguments"]
        else:
            logger.typewriter_log("message_to_tool_node warning: no function_call in message",Fore.RED)

        return new_node