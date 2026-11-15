export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[];

export type MessageRole = 'system' | 'user' | 'assistant' | 'tool';

export type Database = {
  public: {
    Tables: {
      conversations: {
        Row: {
          id: string;
          user_id: string;
          title: string;
          created_at: string;
        };
        Insert: {
          id?: string;
          user_id: string;
          title?: string;
          created_at?: string;
        };
        Update: {
          id?: string;
          user_id?: string;
          title?: string;
          created_at?: string;
        };
        Relationships: [];
      };
      messages: {
        Row: {
          id: string;
          conversation_id: string;
          role: MessageRole;
          content: string;
          tool_calls: Json | null;
          created_at: string;
        };
        Insert: {
          id?: string;
          conversation_id: string;
          role: MessageRole;
          content?: string;
          tool_calls?: Json | null;
          created_at?: string;
        };
        Update: {
          id?: string;
          conversation_id?: string;
          role?: MessageRole;
          content?: string;
          tool_calls?: Json | null;
          created_at?: string;
        };
        Relationships: [
          {
            foreignKeyName: 'messages_conversation_id_fkey';
            columns: ['conversation_id'];
            isOneToOne: false;
            referencedRelation: 'conversations';
            referencedColumns: ['id'];
          },
        ];
      };
    };
    Views: { [_ in never]: never };
    Functions: { [_ in never]: never };
    Enums: { [_ in never]: never };
    CompositeTypes: { [_ in never]: never };
  };
};

export type ConversationRow = Database['public']['Tables']['conversations']['Row'];
export type MessageRow = Database['public']['Tables']['messages']['Row'];
export type MessageInsert = Database['public']['Tables']['messages']['Insert'];
